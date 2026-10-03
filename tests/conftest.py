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
# Postgres ficticio: los tests usan SQLite en memoria y, al ganarle al .env, nunca tocan Neon
os.environ.setdefault("POSTGRES_HOST", "postgres.test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("POSTGRES_DB", "kinesiapp_test")
# Sin credenciales de almacenamiento, aunque el .env tenga las de Neon: si un test olvidara el
# fake, la subida respondería 503 en vez de escribir en el bucket real
for _storage_variable in ("AWS_ENDPOINT_URL_S3", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
    os.environ[_storage_variable] = ""
SERVICE_API_KEY = "test-service-api-key"
# Contenido del video de prueba: distinto byte a byte para verificar lo que se reproduce
VIDEO_BYTES = bytes(range(256)) * 16
os.environ["JUMP_ANALYSIS_SERVICE_API_KEY"] = SERVICE_API_KEY

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db, get_session_factory
from app.main import app
from app.models.user import User, UserRole
from app.schemas.jump_analysis import JointAngleMeasurementCreate, JumpAnalysisResultIngest
from app.services.chat_factory import get_llm_client
from app.services.jump_video_analyzer_factory import get_jump_video_analyzer
from app.services.jump_video_storage import JumpVideoStorage
from app.services.object_storage_factory import get_video_object_storage
from app.storage.object_storage import ObjectStorageError

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
# Las tareas en segundo plano abren su propia sesión: también contra la DB de tests
app.dependency_overrides[get_session_factory] = lambda: TestingSessionLocal


class _StubJumpVideoAnalyzer:
    """Los tests de API suben bytes que no son un video: el análisis real se prueba aparte
    (tests/test_analysis_*.py), aquí sólo importa el ciclo de vida del análisis."""

    def analyze(self, video_path, movement_type):
        return JumpAnalysisResultIngest(
            risk_score=0.5,
            dominant_risk_pattern="forward_collapse",
            pose_model_version="pose-stub",
            risk_model_version="risk-stub",
            measurements=[JointAngleMeasurementCreate(joint_name="knee_flexion", angle_degrees=40, frame_timestamp_ms=0)],
        )


app.dependency_overrides[get_jump_video_analyzer] = _StubJumpVideoAnalyzer


class FakeLlmClient:
    """Sustituye a Gemini en los tests: nunca se llama a la API real."""

    def __init__(self) -> None:
        self.requests = []
        self.reply = "Respuesta de prueba del asistente."
        self.error: Exception | None = None

    def generate_reply(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.reply


class FakeObjectStorage:
    """Sustituye al almacenamiento de Neon en los tests: los objetos viven en memoria, sin red."""

    PUBLIC_BASE_URL = "https://storage.test/videos/"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.error: Exception | None = None

    def upload(self, source, key, content_type):
        if self.error is not None:
            raise self.error
        url = self.PUBLIC_BASE_URL + key
        self.objects[url] = (source.read(), content_type)
        return url

    def download(self, public_url, destination):
        if public_url not in self.objects:
            raise ObjectStorageError(f"No object at {public_url}")
        destination.write_bytes(self.objects[public_url][0])

    def delete(self, public_url):
        if self.error is not None:
            raise self.error
        self.objects.pop(public_url, None)


@pytest.fixture(autouse=True)
def fake_object_storage():
    # autouse: casi todos los tests de API suben un video
    fake = FakeObjectStorage()
    app.dependency_overrides[get_video_object_storage] = lambda: fake
    yield fake
    del app.dependency_overrides[get_video_object_storage]


@pytest.fixture
def jump_video_storage(fake_object_storage):
    return JumpVideoStorage(fake_object_storage, settings.MAX_VIDEO_UPLOAD_BYTES)


@pytest.fixture
def fake_llm():
    fake = FakeLlmClient()
    app.dependency_overrides[get_llm_client] = lambda: fake
    yield fake
    del app.dependency_overrides[get_llm_client]


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

    def _do(email: str, password: str = "supersecret1", role: str = "athlete") -> str:
        r = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Test User", "role": role},
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


@pytest.fixture
def grant_consent(client):
    """Acepta la versión vigente del consentimiento de video para ese usuario."""

    def _do(token: str) -> None:
        r = client.post(
            "/api/v1/users/me/video-consent",
            json={"version": settings.VIDEO_CONSENT_VERSION},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text

    return _do


@pytest.fixture
def upload_jump(client):
    """Sube un video de salto mínimo por POST /jump-analyses/upload y devuelve la respuesta."""

    def _do(token: str, athlete_id: int, content_type: str = "video/mp4", movement_type: str | None = None):
        data = {"athlete_id": str(athlete_id)}
        if movement_type is not None:
            data["movement_type"] = movement_type
        return client.post(
            "/api/v1/jump-analyses/upload",
            data=data,
            files={"video": ("jump.mp4", VIDEO_BYTES, content_type)},
            headers={"Authorization": f"Bearer {token}"},
        )

    return _do
