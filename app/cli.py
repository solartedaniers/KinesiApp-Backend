"""Admin CLI. Usage: python -m app.cli create-admin

Credentials come from ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_FULL_NAME env vars,
or are prompted interactively (password via getpass, never echoed or logged).
"""
import argparse
import getpass
import os

from sqlalchemy import inspect

from app.core.database import SessionLocal, engine
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.user_service import UserService


def _read_credentials() -> tuple[str, str, str]:
    email = os.getenv("ADMIN_EMAIL") or input("Admin email: ").strip()
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    full_name = os.getenv("ADMIN_FULL_NAME") or input("Admin full name: ").strip()
    return email, password, full_name


def _ensure_schema_migrated() -> None:
    # La CLI no crea tablas: si el esquema no está migrado, falla con un
    # mensaje claro en vez de crearlo por su cuenta (eso es trabajo de Alembic).
    if not inspect(engine).has_table(User.__tablename__):
        raise SystemExit(
            "El esquema de la base de datos no está migrado "
            f"(falta la tabla '{User.__tablename__}'). Corré 'alembic upgrade head' primero."
        )


def create_admin() -> None:
    email, password, full_name = _read_credentials()

    _ensure_schema_migrated()
    db = SessionLocal()
    try:
        repository = UserRepository(db)
        service = UserService(repository)

        user = repository.get_by_email(email)
        if user is None:
            user = service.create_user(UserCreate(email=email, password=password, full_name=full_name))

        # Idempotente: si ya existía, sólo lo promueve; no toca su contraseña
        user = service.set_role(user.id, UserRole.ADMIN)
        if not user.is_verified:
            user.is_verified = True
            repository.add(user)

        print(f"'{email}' is now ADMIN.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create-admin", help="Create a user as ADMIN, or promote it if it already exists")

    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin()


if __name__ == "__main__":
    main()
