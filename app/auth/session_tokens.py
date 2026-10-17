import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from pydantic import BaseModel, ValidationError

from app.core.domain_error import DomainError
from app.settings.auth import AuthSettings


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


class _RefreshTokenClaims(BaseModel):
    sub: int
    type: Literal["refresh"]


class SessionTokenService:
    """Firmo los JWT de sesión con el mismo formato del REST, para que ambos acepten los tokens del otro."""

    def __init__(self, settings: AuthSettings) -> None:
        self._secret = settings.JWT_SECRET_KEY.get_secret_value()
        self._algorithm = settings.JWT_ALGORITHM
        self._access_lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        self._refresh_lifetime = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    def issue(self, user_id: int) -> SessionTokens:
        now = datetime.now(timezone.utc)
        access_expires_at = now + self._access_lifetime
        refresh_expires_at = now + self._refresh_lifetime
        access = {"sub": str(user_id), "type": "access", "iat": now, "exp": access_expires_at}
        # Agrego jti porque dos refresh del mismo segundo serían idénticos y chocarían con el UNIQUE de token_hash
        refresh = {"sub": str(user_id), "type": "refresh", "iat": now, "exp": refresh_expires_at,
                   "jti": secrets.token_hex(16)}
        return SessionTokens(
            access_token=jwt.encode(access, self._secret, algorithm=self._algorithm),
            access_token_expires_at=access_expires_at,
            refresh_token=jwt.encode(refresh, self._secret, algorithm=self._algorithm),
            refresh_token_expires_at=refresh_expires_at,
        )

    def refresh_token_subject(self, refresh_token: str) -> int:
        try:
            claims = _RefreshTokenClaims.model_validate(
                jwt.decode(refresh_token, self._secret, algorithms=[self._algorithm])
            )
        except (jwt.PyJWTError, ValidationError) as error:
            raise _invalid_refresh_token() from error
        return claims.sub

    @staticmethod
    def fingerprint(refresh_token: str) -> str:
        # Guardo el hash del refresh token, nunca el valor, por si la base se filtra
        return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _invalid_refresh_token() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_INVALID_REFRESH_TOKEN, "Refresh token is invalid, expired or revoked")
