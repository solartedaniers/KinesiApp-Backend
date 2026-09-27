from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    ConflictException,
    ErrorCode,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_otp_code,
    hash_otp_code,
    hash_password,
    hash_token,
    verify_otp_code,
    verify_password,
)
from app.core.time_utils import is_expired
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenPair
from app.schemas.user import UserCreate


class AuthService:
    """Orquesta registro, verificación por OTP, login, sesiones (JWT) y recuperación de contraseña."""

    def __init__(self, user_repository: UserRepository, refresh_token_repository: RefreshTokenRepository) -> None:
        self._users = user_repository
        self._refresh_tokens = refresh_token_repository

    def register(self, data: UserCreate) -> tuple[User, str]:
        existing_user = self._users.get_by_email(data.email)
        if existing_user is not None and existing_user.is_verified:
            raise ConflictException(
                f"Email '{data.email}' is already registered", code=ErrorCode.EMAIL_ALREADY_REGISTERED
            )

        user = existing_user or User(email=data.email)
        user.hashed_password = hash_password(data.password)
        user.full_name = data.full_name
        user.role = data.role
        user.is_active = False
        user.is_verified = False
        code = self._assign_verification_code(user)
        return self._users.add(user), code

    def request_verification_code(self, email: str) -> str | None:
        user = self._users.get_by_email(email)
        if user is None or user.is_verified:
            return None
        code = self._assign_verification_code(user)
        self._users.add(user)
        return code

    def verify_email(self, email: str, code: str) -> TokenPair:
        user = self._get_user_by_email(email)
        self._validate_otp(
            user,
            code,
            user.verification_code_hash,
            user.verification_code_expires_at,
            user.verification_code_attempts,
            "verification_code_attempts",
        )

        user.is_verified = True
        user.is_active = True
        user.verification_code_hash = None
        user.verification_code_expires_at = None
        user.verification_code_attempts = 0
        self._users.add(user)
        return self._issue_tokens(user)

    def login(self, email: str, password: str) -> TokenPair:
        user = self._users.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise UnauthorizedException("Incorrect email or password", code=ErrorCode.INVALID_CREDENTIALS)
        if not user.is_active:
            raise ForbiddenException("Account is disabled", code=ErrorCode.ACCOUNT_DISABLED)
        if not user.is_verified:
            raise ForbiddenException("You must verify your email before logging in", code=ErrorCode.EMAIL_NOT_VERIFIED)

        return self._issue_tokens(user)

    def refresh(self, raw_refresh_token: str) -> TokenPair:
        payload = decode_token(raw_refresh_token, expected_type="refresh")
        stored = self._refresh_tokens.get_by_token_hash(hash_token(raw_refresh_token))
        if stored is None or not stored.is_active or stored.user_id != int(payload["sub"]):
            raise UnauthorizedException(
                "Refresh token is invalid, expired or revoked", code=ErrorCode.INVALID_REFRESH_TOKEN
            )

        # Rotación: el token usado se revoca de inmediato, así un refresh token reutilizado no sirve
        self._refresh_tokens.revoke(stored)
        user = self._get_user_by_id(stored.user_id)
        return self._issue_tokens(user)

    def logout(self, raw_refresh_token: str) -> None:
        # Idempotente: si el token no existe o ya estaba revocado, el resultado deseado ya se cumple
        stored = self._refresh_tokens.get_by_token_hash(hash_token(raw_refresh_token))
        if stored is not None and stored.is_active:
            self._refresh_tokens.revoke(stored)

    def request_password_reset(self, email: str) -> str | None:
        user = self._users.get_by_email(email)
        if user is None:
            return None  # el endpoint responde igual para no filtrar qué emails existen

        code = generate_otp_code()
        user.password_reset_code_hash = hash_otp_code(code)
        user.password_reset_code_attempts = 0
        user.password_reset_code_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.OTP_EXPIRE_MINUTES
        )
        self._users.add(user)
        return code

    def verify_password_reset_code(self, email: str, code: str) -> None:
        """Paso 2 de la recuperación: valida el OTP sin consumirlo (los fallos sí cuentan)."""
        user = self._users.get_by_email(email)
        if user is None:
            # Mismo error que un código incorrecto: no revela qué emails existen
            raise UnauthorizedException("Invalid or expired verification code", code=ErrorCode.INVALID_OTP)
        self._validate_reset_code(user, code)

    def confirm_password_reset(self, email: str, code: str, new_password: str) -> None:
        user = self._get_user_by_email(email)
        self._validate_reset_code(user, code)

        self._replace_password(user, new_password)
        user.password_reset_code_hash = None
        user.password_reset_code_expires_at = None
        user.password_reset_code_attempts = 0
        self._users.add(user)
        # Cambiar la contraseña invalida cualquier sesión previa (dispositivos robados/perdidos)
        self._refresh_tokens.revoke_all_for_user(user.id)

    def change_password(self, user: User, current_password: str, new_password: str) -> TokenPair:
        """Cambio con sesión iniciada: exige la actual y emite tokens nuevos para este dispositivo."""
        if not verify_password(current_password, user.hashed_password):
            # 400 y no 401: un 401 dispararía el refresh de tokens en el cliente
            raise AppException("Current password is incorrect", code=ErrorCode.INVALID_CURRENT_PASSWORD)
        self._replace_password(user, new_password)
        self._users.add(user)
        self._refresh_tokens.revoke_all_for_user(user.id)
        return self._issue_tokens(user)

    def _replace_password(self, user: User, new_password: str) -> None:
        # Se compara contra el hash bcrypt guardado: la contraseña nunca existe en texto plano
        if verify_password(new_password, user.hashed_password):
            raise ConflictException(
                "New password must be different from the current one", code=ErrorCode.PASSWORD_REUSED
            )
        user.hashed_password = hash_password(new_password)

    def _validate_reset_code(self, user: User, code: str) -> None:
        self._validate_otp(
            user,
            code,
            user.password_reset_code_hash,
            user.password_reset_code_expires_at,
            user.password_reset_code_attempts,
            "password_reset_code_attempts",
        )

    def _issue_tokens(self, user: User) -> TokenPair:
        access_token = create_access_token(user.id)
        raw_refresh_token, expires_at = create_refresh_token(user.id)
        self._refresh_tokens.add(
            RefreshToken(user_id=user.id, token_hash=hash_token(raw_refresh_token), expires_at=expires_at)
        )
        return TokenPair(access_token=access_token, refresh_token=raw_refresh_token)

    def _assign_verification_code(self, user: User) -> str:
        code = generate_otp_code()
        user.verification_code_hash = hash_otp_code(code)
        user.verification_code_attempts = 0
        user.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.OTP_EXPIRE_MINUTES
        )
        return code

    def _validate_otp(
        self,
        user: User,
        code: str,
        code_hash: str | None,
        expires_at: datetime | None,
        attempts: int,
        attempts_field: str,
    ) -> None:
        invalid = (
            code_hash is None
            or expires_at is None
            or is_expired(expires_at)
            or attempts >= settings.OTP_MAX_ATTEMPTS
        )
        if invalid:
            raise UnauthorizedException("Invalid or expired verification code", code=ErrorCode.INVALID_OTP)
        if not verify_otp_code(code, code_hash):
            setattr(user, attempts_field, attempts + 1)
            self._users.add(user)
            raise UnauthorizedException("Invalid or expired verification code", code=ErrorCode.INVALID_OTP)

    def _get_user_by_email(self, email: str) -> User:
        user = self._users.get_by_email(email)
        if user is None:
            raise NotFoundException("User", email)
        return user

    def _get_user_by_id(self, user_id: int) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundException("User", user_id)
        return user
