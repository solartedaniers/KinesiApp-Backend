"""CLI de administración: alta/promoción idempotente a ADMIN (app/cli.py)."""
from app.cli import create_admin
from app.models.user import User, UserRole
from tests.conftest import TestingSessionLocal, engine


def _run_create_admin(monkeypatch, email: str) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", email)
    monkeypatch.setenv("ADMIN_PASSWORD", "supersecret1")
    monkeypatch.setenv("ADMIN_FULL_NAME", "Admin User")
    # La CLI usa su propia sesión (no pasa por get_db); se redirige a la DB de test
    monkeypatch.setattr("app.cli.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.cli.engine", engine)
    create_admin()


def test_create_admin_creates_new_verified_admin(monkeypatch, db_session):
    _run_create_admin(monkeypatch, "root@kinesiapp.com")

    user = db_session.query(User).filter(User.email == "root@kinesiapp.com").one()
    assert user.role == UserRole.ADMIN
    assert user.is_verified is True


def test_create_admin_promotes_existing_user_without_touching_password(monkeypatch, db_session):
    db_session.add(
        User(
            email="future-admin@kinesiapp.com",
            hashed_password="original-hash",
            full_name="Someone",
            role=UserRole.ATHLETE,
        )
    )
    db_session.commit()

    _run_create_admin(monkeypatch, "future-admin@kinesiapp.com")

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == "future-admin@kinesiapp.com").one()
    assert user.role == UserRole.ADMIN
    assert user.hashed_password == "original-hash"


def test_create_admin_is_idempotent(monkeypatch, db_session):
    _run_create_admin(monkeypatch, "twice@kinesiapp.com")
    _run_create_admin(monkeypatch, "twice@kinesiapp.com")

    users = db_session.query(User).filter(User.email == "twice@kinesiapp.com").all()
    assert len(users) == 1
    assert users[0].role == UserRole.ADMIN
