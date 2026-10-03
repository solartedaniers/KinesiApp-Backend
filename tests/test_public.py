"""Endpoints públicos y normalización del content_type de video (cliente web)."""
from io import BytesIO

from app.core.config import settings
from tests.conftest import VIDEO_BYTES


def test_video_consent_version_is_public(client, monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_CONSENT_VERSION", 3)
    r = client.get("/api/v1/public/video-consent")
    assert r.status_code == 200
    assert r.json() == {"version": 3}


def test_storage_ignores_content_type_parameters(jump_video_storage, fake_object_storage):
    # MediaRecorder etiqueta el Blob con codecs; antes esto guardaba un .bin
    for content_type, media_type, suffix in [
        ("video/webm;codecs=vp8,opus", "video/webm", ".webm"),
        ("video/mp4; codecs=avc1", "video/mp4", ".mp4"),
        ("video/webm", "video/webm", ".webm"),
    ]:
        url = jump_video_storage.save(BytesIO(VIDEO_BYTES), content_type)
        assert url.endswith(suffix)
        assert fake_object_storage.objects[url] == (VIDEO_BYTES, media_type)

