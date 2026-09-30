"""Endpoints públicos y normalización del content_type de video (cliente web)."""
from io import BytesIO

from app.core.config import settings
from app.services.jump_video_storage import JumpVideoStorage
from tests.conftest import VIDEO_BYTES


def test_video_consent_version_is_public(client, monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_CONSENT_VERSION", 3)
    r = client.get("/api/v1/public/video-consent")
    assert r.status_code == 200
    assert r.json() == {"version": 3}


def test_storage_ignores_content_type_parameters(tmp_path):
    # MediaRecorder etiqueta el Blob con codecs; antes esto guardaba un .bin
    storage = JumpVideoStorage(tmp_path, 10_000)
    for content_type, suffix in [
        ("video/webm;codecs=vp8,opus", ".webm"),
        ("video/mp4; codecs=avc1", ".mp4"),
        ("video/webm", ".webm"),
    ]:
        path = storage.save(BytesIO(VIDEO_BYTES), content_type)
        assert path.suffix == suffix
        assert path.read_bytes() == VIDEO_BYTES

