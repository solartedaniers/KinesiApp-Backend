"""Subida de video en streaming + procesamiento en segundo plano (BackgroundTasks)."""
from pathlib import Path

from app.core.config import settings
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile


def _upload(client, token: str, athlete_id: int, content_type: str = "video/mp4"):
    return client.post(
        "/api/v1/jump-analyses/upload",
        data={"athlete_id": str(athlete_id)},
        files={"video": ("jump.mp4", b"\x00" * 4096, content_type)},
        headers=_auth_headers(token),
    )


def test_upload_answers_pending_and_processes_in_background(client, register_and_verify):
    token = register_and_verify("uploader@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)

    r = _upload(client, token, athlete_id)
    assert r.status_code == 202, r.text
    # La respuesta sale antes del procesamiento: todavía PENDING
    assert r.json()["status"] == "pending"
    assert Path(r.json()["video_reference"]).stat().st_size == 4096

    # TestClient ejecuta las BackgroundTasks antes de devolver el control
    r = client.get(f"/api/v1/jump-analyses/{r.json()['id']}", headers=_auth_headers(token))
    assert r.json()["status"] == "processed"
    assert 0 <= r.json()["risk_score"] <= 1
    assert r.json()["angle_measurements"]


def test_upload_rejects_non_video_and_oversized_files(client, register_and_verify, monkeypatch):
    token = register_and_verify("uploader2@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)

    r = _upload(client, token, athlete_id, content_type="image/png")
    assert (r.status_code, r.json()["code"]) == (415, "invalid_video")

    stored_before = set(settings.VIDEO_UPLOAD_DIR.glob("*"))
    monkeypatch.setattr(settings, "MAX_VIDEO_UPLOAD_BYTES", 1024)
    r = _upload(client, token, athlete_id)
    assert (r.status_code, r.json()["code"]) == (413, "video_too_large")
    # El archivo a medio escribir se borra
    assert set(settings.VIDEO_UPLOAD_DIR.glob("*")) == stored_before


def test_other_athlete_cannot_upload(client, register_and_verify):
    owner_token = register_and_verify("owner-up@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, owner_token)
    intruder_token = register_and_verify("intruder-up@kinesiapp.com")

    assert _upload(client, intruder_token, athlete_id).status_code == 403
