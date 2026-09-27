"""Fixtures compartidas: una sola DB SQLite en memoria, reseteada por test."""
import os

# Config SMTP de prueba: no se conecta a internet; SmtpEmailSender queda reemplazado
# por el fixture email_outbox antes de enviar correos.
os.environ.setdefault("SMTP_HOST", "smtp.test")
os.environ.setdefault("SMTP_PORT", "587")
os.environ.setdefault("SMTP_USER", "test@kinesiapp.test")
os.environ.setdefault("SMTP_PASSWORD", "test-password")
os.environ.setdefault("SMTP_FROM_NAME", "KinesiApp Test")
os.environ.setdefault("OTP_EXPIRE_MINUTES", "10")

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.user import User, UserRole

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def email_outbox(monkeypatch):
    messages = []

    def capture_email(sender, recipient, subject, body):
        messages.append({"to": recipient, "subject": subject, "body": body})

    monkeypatch.setattr("app.core.email.SmtpEmailSender.send", capture_email)
    return messages


@pytest.fixture
def db_session():
    # Para que un test pueda leer/mutar filas directamente (p. ej. un código OTP que solo llega por email)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def register_and_verify(client, db_session, email_outbox):
    """Factory fixture: registra un usuario, lee su OTP de la DB (no hay SMTP en tests),
    lo verifica y devuelve el access token. Compartida por todos los tests que necesitan
    un usuario autenticado sin repetir el flujo completo de /auth en cada archivo."""

    def _do(email: str, password: str = "supersecret1") -> str:
        r = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Test User"},
        )
        assert r.status_code == 201, r.text

        message = next(item for item in reversed(email_outbox) if item["to"] == email)
        code = re.search(r"\b\d{6}\b", message["body"]).group()
        r = client.post(
            "/api/v1/auth/verify-email", json={"email": email, "code": code}
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    return _do


@pytest.fixture
def set_role(db_session):
    """Sólo para tests: en producción el ascenso a COACH/ADMIN pasa por PATCH /users/{id}/role."""

    def _do(email: str, role: UserRole) -> None:
        user = db_session.query(User).filter(User.email == email).one()
        user.role = role
        db_session.commit()

    return _do
