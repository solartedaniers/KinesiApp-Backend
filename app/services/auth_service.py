from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.exceptions import (
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
    hash_password,
    hash_token,
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

    def register(self, data: UserCreate) -> User:
        if self._users.get_by_email(data.email) is not None:
            raise ConflictException(
                f"Email '{data.email}' is already registered", code=ErrorCode.EMAIL_ALREADY_REGISTERED
            )

        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
        )
        self._assign_verification_code(user)
        return self._users.add(user)

    def verify_email(self, email: str, code: str) -> TokenPair:
        user = self._get_user_by_email(email)
        if (
            user.verification_code != code
            or user.verification_code_expires_at is None
            or is_expired(user.verification_code_expires_at)
        ):
            raise UnauthorizedException("Invalid or expired verification code", code=ErrorCode.INVALID_OTP)

        user.is_verified = True
        user.verification_code = None
        user.verification_code_expires_at = None
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
        user.password_reset_code = code
        user.password_reset_code_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.OTP_EXPIRE_MINUTES
        )
        self._users.add(user)
        return code

    def confirm_password_reset(self, email: str, code: str, new_password: str) -> None:
        user = self._get_user_by_email(email)
        if (
            user.password_reset_code != code
            or user.password_reset_code_expires_at is None
            or is_expired(user.password_reset_code_expires_at)
        ):
            raise UnauthorizedException("Invalid or expired recovery code", code=ErrorCode.INVALID_OTP)

        user.hashed_password = hash_password(new_password)
        user.password_reset_code = None
        user.password_reset_code_expires_at = None
        self._users.add(user)
        # Cambiar la contraseña invalida cualquier sesión previa (dispositivos robados/perdidos)
        self._refresh_tokens.revoke_all_for_user(user.id)

    def _issue_tokens(self, user: User) -> TokenPair:
        access_token = create_access_token(user.id)
        raw_refresh_token, expires_at = create_refresh_token(user.id)
        self._refresh_tokens.add(
            RefreshToken(user_id=user.id, token_hash=hash_token(raw_refresh_token), expires_at=expires_at)
        )
        return TokenPair(access_token=access_token, refresh_token=raw_refresh_token)

    def _assign_verification_code(self, user: User) -> None:
        user.verification_code = generate_otp_code()
        user.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.OTP_EXPIRE_MINUTES
        )

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
