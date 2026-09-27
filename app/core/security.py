import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ErrorCode, ForbiddenException, UnauthorizedException
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer(auto_error=True)
# Header propio para procesos internos: no se mezcla con el JWT de los usuarios
_service_api_key_scheme = APIKeyHeader(name="X-Service-Api-Key", auto_error=False)

TokenType = Literal["access", "refresh", "video"]


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def hash_otp_code(code: str) -> str:
    """Guarda OTPs con bcrypt: un volcado de DB no revela códigos vigentes."""
    return _pwd_context.hash(code)


def verify_otp_code(code: str, code_hash: str) -> bool:
    try:
        return _pwd_context.verify(code, code_hash)
    except (ValueError, TypeError):
        return False


def generate_otp_code() -> str:
    # 6 dígitos numéricos: suficiente entropía para un código de un solo uso de vida corta
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_token(raw_token: str) -> str:
    # Se persiste el hash del refresh token, nunca el valor crudo, por si la DB se filtra
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "type": token_type, "iat": now, "exp": now + expires_delta}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(
        str(user_id), "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    # jti evita que dos refresh tokens emitidos en el mismo segundo (mismo sub/iat/exp)
    # generen el mismo JWT y choquen contra el UNIQUE de token_hash
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": now,
        "exp": expires_at,
        "jti": secrets.token_hex(16),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def create_video_access_token(analysis_id: int) -> tuple[str, datetime]:
    # Sólo sirve para GET /jump-analyses/{analysis_id}/video: tipo "video" (get_current_user
    # lo rechaza como access token) y el sub es el análisis, no un usuario
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.VIDEO_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(analysis_id), "type": "video", "exp": expires_at}
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def verify_video_access_token(token: str, analysis_id: int) -> None:
    if decode_token(token, expected_type="video").get("sub") != str(analysis_id):
        raise UnauthorizedException("Token is not valid for this video")


def decode_token(token: str, expected_type: TokenType) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise UnauthorizedException("Invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise UnauthorizedException("Incorrect token type")
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    # Dependencia de autorización: valida el access token y resuelve el usuario autenticado
    payload = decode_token(credentials.credentials, expected_type="access")
    user = UserRepository(db).get(int(payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedException("User does not exist or is inactive")
    return user


def require_roles(*allowed_roles: UserRole):
    """Fábrica de dependencia RBAC: exige que el usuario autenticado tenga uno de los roles dados."""

    def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenException("You don't have permission to perform this operation")
        return current_user

    return _check_role


def require_service_api_key(api_key: str | None = Depends(_service_api_key_scheme)) -> None:
    """Autentica a un proceso interno (no a una persona) por API key de servicio."""
    configured = settings.JUMP_ANALYSIS_SERVICE_API_KEY
    expected = configured.get_secret_value() if configured else ""
    # Clave vacía = no configurada: nunca se acepta un header vacío contra una clave vacía.
    # compare_digest: tiempo constante, no filtra cuántos caracteres coinciden
    if not expected or not api_key or not secrets.compare_digest(api_key.encode(), expected.encode()):
        raise UnauthorizedException("Invalid service API key", code=ErrorCode.INVALID_SERVICE_API_KEY)
