"""Prueba de humo end-to-end: cubre el flujo completo user -> athlete -> jump analysis."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

# SQLite en memoria con StaticPool: una sola conexión compartida por todo el test
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


client = TestClient(app)


def test_full_flow():
    assert client.get("/health").status_code == 200

    r = client.post(
        "/api/v1/users", json={"email": "a@a.com", "password": "12345678", "full_name": "Ana"}
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    # Email duplicado debe rechazarse con 409
    r = client.post(
        "/api/v1/users", json={"email": "a@a.com", "password": "12345678", "full_name": "Ana"}
    )
    assert r.status_code == 409

    r = client.post(
        "/api/v1/athletes",
        json={
            "user_id": user_id,
            "sport": "running",
            "height_cm": 170,
            "weight_kg": 65,
            "birth_date": "2000-01-01",
        },
    )
    assert r.status_code == 201, r.text
    athlete_id = r.json()["id"]

    r = client.post(
        "/api/v1/jump-analyses", json={"athlete_id": athlete_id, "video_reference": "s3://video.mp4"}
    )
    assert r.status_code == 201, r.text
    analysis_id = r.json()["id"]
    assert r.json()["status"] == "pending"

    # Simula al pipeline de IA reportando el resultado del salto
    r = client.post(
        f"/api/v1/jump-analyses/{analysis_id}/results",
        json={
            "risk_score": 0.42,
            "measurements": [{"joint_name": "knee", "angle_degrees": 145.5, "frame_timestamp_ms": 120}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "processed"
    assert r.json()["angle_measurements"][0]["joint_name"] == "knee"

    assert client.get("/api/v1/jump-analyses/99999").status_code == 404
