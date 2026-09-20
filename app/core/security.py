import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import UnauthorizedException
from app.models.user import User
from app.repositories.user_repository import UserRepository

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer(auto_error=True)

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def generate_otp_code() -> str:
    # 6 dígitos numéricos: suficiente entropía para un código de un solo uso de vida corta
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_token(raw_token: str) -> str:
    # Se persiste el hash del refresh token, nunca el valor crudo, por si la DB se filtra
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def is_expired(expires_at: datetime) -> bool:
    # SQLite (usada en tests) no conserva tzinfo al leer un DateTime(timezone=True);
    # se asume UTC si viene naive para poder comparar sin TypeError en cualquier motor
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)


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


def decode_token(token: str, expected_type: TokenType) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise UnauthorizedException("Token inválido o expirado") from exc

    if payload.get("type") != expected_type:
        raise UnauthorizedException("Tipo de token incorrecto")
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    # Dependencia de autorización: valida el access token y resuelve el usuario autenticado
    payload = decode_token(credentials.credentials, expected_type="access")
    user = UserRepository(db).get(int(payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedException("Usuario inexistente o inactivo")
    return user
