import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  registra todos los modelos en Base.metadata
from app.core.async_database import build_session_factory
from app.core.domain_error import DomainError
from app.identity.access_tokens import JwtAccessTokenVerifier
from app.identity.principal import Principal
from app.models.base import Base
from app.models.user import User, UserRole
from app.settings.auth import AuthSettings

SECRET = "access-token-test-secret"


def _token(sub: str, token_type: str = "access", expires_in: timedelta = timedelta(minutes=5)) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": sub, "type": token_type, "iat": now, "exp": now + expires_in}, SECRET, algorithm="HS256")


async def _verify(token: str) -> Principal:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = build_session_factory(engine)
    async with session_factory() as session:
        session.add_all([
            User(id=1, email="coach@kinesiapp.com", hashed_password="x", full_name="Coach", role=UserRole.COACH),
            User(id=2, email="off@kinesiapp.com", hashed_password="x", full_name="Off", is_active=False),
        ])
        await session.commit()
    settings = AuthSettings(_env_file=None, JWT_SECRET_KEY=SECRET, OTP_EXPIRE_MINUTES=10)
    try:
        return await JwtAccessTokenVerifier(settings, session_factory).verify(token)
    finally:
        await engine.dispose()


def test_valid_access_token_resolves_an_active_user() -> None:
    assert asyncio.run(_verify(_token("1"))) == Principal(user_id=1, role=UserRole.COACH)


@pytest.mark.parametrize(
    "token",
    [
        _token("2"),
        _token("99"),
        _token("1", token_type="refresh"),
        _token("1", expires_in=timedelta(minutes=-1)),
        jwt.encode({"sub": "1", "type": "access"}, "another-secret-with-enough-length", algorithm="HS256"),
        "not-a-jwt",
    ],
    ids=["inactive", "unknown-user", "refresh-token", "expired", "foreign-signature", "garbage"],
)
def test_rejected_tokens_raise_unauthorized(token: str) -> None:
    with pytest.raises(DomainError) as raised:
        asyncio.run(_verify(token))

    assert raised.value.reason == ErrorReason.ERROR_REASON_UNAUTHORIZED
