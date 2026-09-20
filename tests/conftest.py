"""Fixtures compartidas: una sola DB SQLite en memoria, reseteada por test."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

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
def db_session():
    # Para que un test pueda leer/mutar filas directamente (p. ej. un código OTP que solo llega por email)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
