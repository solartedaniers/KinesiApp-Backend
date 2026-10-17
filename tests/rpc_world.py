"""Base común de las pruebas gRPC: SQLite asíncrono en un archivo, interceptores reales y usuarios con token."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import grpc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  registra todos los modelos en Base.metadata
from app.auth.session_tokens import SessionTokenService
from app.core.async_database import build_session_factory
from app.identity.access_tokens import JwtAccessTokenVerifier
from app.models.base import Base
from app.models.user import User, UserRole
from app.repositories.unit_of_work import UnitOfWork
from app.rpc.interceptors.auth import AuthInterceptor
from app.rpc.interceptors.errors import ErrorInterceptor
from app.settings.auth import AuthSettings
from app.storage.signed_storage import PresignedRead, PresignedUpload, StoredObject
from tests.grpc_harness import serving

AUTH_SETTINGS = AuthSettings(_env_file=None, JWT_SECRET_KEY="rpc-world-test-secret-key", OTP_EXPIRE_MINUTES=10)
BUCKET_URL = "https://bucket.test/images/"


@dataclass
class World:
    channel: grpc.aio.Channel
    session_factory: async_sessionmaker[AsyncSession]

    def uow(self) -> UnitOfWork:
        return UnitOfWork(self.session_factory)

    async def user(self, email: str, role: UserRole = UserRole.ATHLETE, **fields: object) -> User:
        async with self.session_factory() as session:
            user = User(email=email, hashed_password="unused", full_name="Persona Prueba", role=role,
                        is_active=True, is_verified=True, **fields)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user


def bearer(user: User) -> tuple[tuple[str, str], ...]:
    return (("authorization", f"Bearer {SessionTokenService(AUTH_SETTINGS).issue(user.id).access_token}"),)


@asynccontextmanager
async def rpc_world(
    database: Path, register: Callable[[async_sessionmaker[AsyncSession]], Callable[[grpc.aio.Server], None]]
) -> AsyncIterator[World]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = build_session_factory(engine)
    interceptors = [ErrorInterceptor(), AuthInterceptor(JwtAccessTokenVerifier(AUTH_SETTINGS, session_factory))]
    try:
        async with serving(register(session_factory), interceptors) as channel:
            yield World(channel, session_factory)
    finally:
        await engine.dispose()


def uow_factory(session_factory: async_sessionmaker[AsyncSession]) -> Callable[[], UnitOfWork]:
    return partial(UnitOfWork, session_factory)


@dataclass
class FakeBucket:
    """Bucket en memoria con las mismas URLs canónicas que guardaría Neon."""

    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    signed_uploads: list[tuple[str, str, int]] = field(default_factory=list)

    def url_for(self, key: str) -> str:
        return BUCKET_URL + key

    def key_from_url(self, object_url: str) -> str:
        if not object_url.startswith(BUCKET_URL):
            raise ValueError("URL does not belong to the bucket")
        return object_url.removeprefix(BUCKET_URL)

    def presign_upload(self, key: str, content_type: str, content_length: int) -> PresignedUpload:
        self.signed_uploads.append((key, content_type, content_length))
        return PresignedUpload(f"{BUCKET_URL}{key}?signature=put", {"Content-Type": content_type}, _soon())

    def presign_read(self, key: str) -> PresignedRead:
        return PresignedRead(f"{BUCKET_URL}{key}?signature=get", _soon())

    async def describe(self, key: str) -> StoredObject | None:
        if key not in self.objects:
            return None
        content, content_type = self.objects[key]
        return StoredObject(size=len(content), content_type=content_type)

    async def read_head(self, key: str, length: int) -> bytes:
        return self.objects[key][0][:length]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def browser_put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = (content, content_type)


def _soon() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=5)
