from typing import Literal, Protocol

import jwt
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.repositories.async_user_repository import AsyncUserRepository
from app.settings.auth import AuthSettings


class AccessTokenClaims(BaseModel):
    sub: int
    type: Literal["access"]


class AccessTokenVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...


class JwtAccessTokenVerifier:
    """Valido un access token firmado por este backend y resuelvo un usuario activo."""

    def __init__(self, settings: AuthSettings, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._settings = settings
        self._session_factory = session_factory

    async def verify(self, token: str) -> Principal:
        claims = self._decode(token)
        async with self._session_factory() as session:
            user = await AsyncUserRepository(session).get(claims.sub)
        if user is None or not user.is_active:
            raise DomainError(ErrorReason.ERROR_REASON_UNAUTHORIZED, "User does not exist or is inactive")
        return Principal(user_id=user.id, role=user.role)

    def _decode(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token, self._settings.JWT_SECRET_KEY.get_secret_value(), algorithms=[self._settings.JWT_ALGORITHM]
            )
            return AccessTokenClaims.model_validate(payload)
        except (jwt.PyJWTError, ValidationError) as error:
            raise DomainError(ErrorReason.ERROR_REASON_UNAUTHORIZED, "Invalid or expired access token") from error
