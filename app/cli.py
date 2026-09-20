"""Admin CLI. Usage: python -m app.cli create-admin

Credentials come from ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_FULL_NAME env vars,
or are prompted interactively (password via getpass, never echoed or logged).
"""
import argparse
import getpass
import os

from app.core.database import Base, SessionLocal, engine
from app.models.user import UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.user_service import UserService


def _read_credentials() -> tuple[str, str, str]:
    email = os.getenv("ADMIN_EMAIL") or input("Admin email: ").strip()
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    full_name = os.getenv("ADMIN_FULL_NAME") or input("Admin full name: ").strip()
    return email, password, full_name


def create_admin() -> None:
    email, password, full_name = _read_credentials()

    Base.metadata.create_all(bind=engine)
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
