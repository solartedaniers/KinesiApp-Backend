"""CLI de administración. Uso: python -m app.cli create-admin

Tomo las credenciales de ADMIN_EMAIL, ADMIN_PASSWORD y ADMIN_FULL_NAME o las pido en la terminal; la
contraseña va por getpass, así que nunca se muestra ni queda en los logs.
"""
import argparse
import asyncio
import getpass
import os
from functools import partial

from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.admin_bootstrap import AdminBootstrap
from app.admin.inputs import AccountInput, AdminInputRules
from app.auth.password_hasher import PasswordHasher
from app.core.async_database import build_async_engine, build_session_factory
from app.identity.password_policy import PasswordPolicy
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork
from app.settings.auth import PasswordPolicySettings
from app.settings.database import DatabaseSettings


def _read_credentials() -> dict[str, str]:
    return {
        "email": os.getenv("ADMIN_EMAIL") or input("Admin email: ").strip(),
        "password": os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: "),
        "full_name": os.getenv("ADMIN_FULL_NAME") or input("Admin full name: ").strip(),
    }


async def _ensure_schema_migrated(engine: AsyncEngine) -> None:
    # La CLI no crea tablas: si el esquema no está migrado, fallo con un mensaje claro (eso es trabajo de Alembic)
    async with engine.connect() as connection:
        migrated = await connection.run_sync(lambda sync: inspect(sync).has_table(User.__tablename__))
    if not migrated:
        raise SystemExit(f"The database schema is not migrated (table '{User.__tablename__}' is missing). Run 'alembic upgrade head' first.")


async def create_admin(engine: AsyncEngine) -> None:
    rules = AdminInputRules(PasswordPolicy(PasswordPolicySettings()))
    try:
        data = rules.parse(AccountInput, _read_credentials())
    except ValidationError as error:
        raise SystemExit(str(error)) from None

    await _ensure_schema_migrated(engine)
    bootstrap = AdminBootstrap(partial(UnitOfWork, build_session_factory(engine)), PasswordHasher())
    user = await bootstrap.run(data)
    print(f"'{user.email}' is now ADMIN.")


async def _main(command: str) -> None:
    engine = build_async_engine(DatabaseSettings())
    try:
        if command == "create-admin":
            await create_admin(engine)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create-admin", help="Create a user as ADMIN, or promote it if it already exists")
    asyncio.run(_main(parser.parse_args().command))


if __name__ == "__main__":
    main()
