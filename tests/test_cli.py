"""CLI de administración: alta o promoción idempotente a ADMIN (app/cli.py)."""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  registra todos los modelos en Base.metadata
from app.cli import create_admin
from app.models.base import Base
from app.models.user import User, UserRole


@pytest.fixture
def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'cli.db').as_posix()}")

    async def migrate():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(migrate())
    yield engine
    asyncio.run(engine.dispose())


def _run_create_admin(monkeypatch, engine, email: str, password: str = "Supersecret1!") -> None:
    monkeypatch.setenv("ADMIN_EMAIL", email)
    monkeypatch.setenv("ADMIN_PASSWORD", password)
    monkeypatch.setenv("ADMIN_FULL_NAME", "Admin User")
    asyncio.run(create_admin(engine))


def _users(engine, email: str) -> list[User]:
    async def query():
        async with engine.connect() as connection:
            return (await connection.execute(select(User).where(User.email == email))).all()

    return asyncio.run(query())


def test_create_admin_creates_new_verified_admin(monkeypatch, engine):
    _run_create_admin(monkeypatch, engine, "root@kinesiapp.com")

    [user] = _users(engine, "root@kinesiapp.com")
    assert user.role == UserRole.ADMIN
    assert user.is_verified is True
    assert user.is_active is True


def test_create_admin_promotes_existing_user_without_touching_password(monkeypatch, engine):
    async def seed():
        async with engine.begin() as connection:
            await connection.execute(User.__table__.insert().values(
                email="future-admin@kinesiapp.com", hashed_password="original-hash", full_name="Someone",
                role=UserRole.ATHLETE, is_active=True, is_verified=False,
            ))

    asyncio.run(seed())
    _run_create_admin(monkeypatch, engine, "future-admin@kinesiapp.com")

    [user] = _users(engine, "future-admin@kinesiapp.com")
    assert user.role == UserRole.ADMIN
    assert user.hashed_password == "original-hash"


def test_create_admin_is_idempotent(monkeypatch, engine):
    _run_create_admin(monkeypatch, engine, "twice@kinesiapp.com")
    _run_create_admin(monkeypatch, engine, "twice@kinesiapp.com")

    users = _users(engine, "twice@kinesiapp.com")
    assert len(users) == 1
    assert users[0].role == UserRole.ADMIN


def test_create_admin_rejects_a_weak_password(monkeypatch, engine):
    with pytest.raises(SystemExit):
        _run_create_admin(monkeypatch, engine, "weak@kinesiapp.com", password="short")
    assert _users(engine, "weak@kinesiapp.com") == []


def test_create_admin_refuses_an_unmigrated_database(monkeypatch, tmp_path):
    empty = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'empty.db').as_posix()}")
    with pytest.raises(SystemExit, match="alembic upgrade head"):
        _run_create_admin(monkeypatch, empty, "root@kinesiapp.com")
    asyncio.run(empty.dispose())
