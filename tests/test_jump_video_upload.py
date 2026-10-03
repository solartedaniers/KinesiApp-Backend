"""Subida de video en streaming + procesamiento en segundo plano (BackgroundTasks)."""
from pydantic import SecretStr

from app.core.config import settings
from app.models.jump_analysis import JumpAnalysis
from app.storage.object_storage import ObjectStorageError
from tests.conftest import SERVICE_API_KEY, VIDEO_BYTES
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile


def test_upload_answers_pending_and_processes_in_background(
    client, register_and_verify, grant_consent, upload_jump, db_session, fake_object_storage
):
    token = register_and_verify("uploader@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)
    grant_consent(token)

    r = upload_jump(token, athlete_id)
    assert r.status_code == 202, r.text
    # La respuesta sale antes del procesamiento: todavía PENDING
    assert r.json()["status"] == "pending"
    # La URL del video no sale en la respuesta: sólo se entrega por video-access
    assert "video_reference" not in r.json()
    # Se guarda la URL pública del objeto, con el contenido y el tipo del video subido
    video_url = db_session.get(JumpAnalysis, r.json()["id"]).video_reference
    assert fake_object_storage.objects[video_url] == (VIDEO_BYTES, "video/mp4")

    # TestClient ejecuta las BackgroundTasks antes de devolver el control
    r = client.get(f"/api/v1/jump-analyses/{r.json()['id']}", headers=_auth_headers(token))
    assert r.json()["status"] == "processed"
    assert 0 <= r.json()["risk_score"] <= 1
    assert r.json()["angle_measurements"]


def test_upload_rejects_non_video_and_oversized_files(
    client, register_and_verify, monkeypatch, grant_consent, upload_jump, fake_object_storage
):
    token = register_and_verify("uploader2@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)
    grant_consent(token)

    r = upload_jump(token, athlete_id, content_type="image/png")
    assert (r.status_code, r.json()["code"]) == (415, "invalid_video")

    monkeypatch.setattr(settings, "MAX_VIDEO_UPLOAD_BYTES", 1024)
    r = upload_jump(token, athlete_id)
    assert (r.status_code, r.json()["code"]) == (413, "video_too_large")
    # Ninguno de los dos llega al bucket
    assert fake_object_storage.objects == {}


def test_upload_answers_503_when_the_storage_fails(
    client, register_and_verify, grant_consent, upload_jump, fake_object_storage, db_session
):
    token = register_and_verify("uploader3@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)
    grant_consent(token)
    fake_object_storage.error = ObjectStorageError("storage down")

    r = upload_jump(token, athlete_id)
    assert (r.status_code, r.json()["code"]) == (503, "storage_unavailable")
    # Sin video no se crea el análisis
    assert db_session.query(JumpAnalysis).count() == 0


def test_other_athlete_cannot_upload(client, register_and_verify, grant_consent, upload_jump):
    owner_token = register_and_verify("owner-up@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, owner_token)
    intruder_token = register_and_verify("intruder-up@kinesiapp.com")
    grant_consent(intruder_token)

    assert upload_jump(intruder_token, athlete_id).status_code == 403


def test_upload_requires_current_video_consent(client, register_and_verify, grant_consent, upload_jump, monkeypatch):
    token = register_and_verify("no-consent@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)

    r = upload_jump(token, athlete_id)
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")

    grant_consent(token)
    me = client.get("/api/v1/auth/me", headers=_auth_headers(token)).json()
    assert me["video_consent_version"] == settings.VIDEO_CONSENT_VERSION
    assert me["video_consent_given_at"] is not None
    assert upload_jump(token, athlete_id).status_code == 202

    # Si cambia el texto legal, el consentimiento anterior ya no alcanza
    monkeypatch.setattr(settings, "VIDEO_CONSENT_VERSION", settings.VIDEO_CONSENT_VERSION + 1)
    assert upload_jump(token, athlete_id).json()["code"] == "consent_required"


def test_results_webhook_requires_service_api_key(client, register_and_verify, grant_consent, upload_jump):
    token = register_and_verify("webhook@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)
    grant_consent(token)
    analysis_id = upload_jump(token, athlete_id).json()["id"]
    url = f"/api/v1/jump-analyses/{analysis_id}/results"
    payload = {"risk_score": 0.3, "measurements": []}

    for headers in ({}, {"X-Service-Api-Key": "wrong"}, _auth_headers(token)):
        r = client.post(url, json=payload, headers=headers)
        assert (r.status_code, r.json()["code"]) == (401, "invalid_service_api_key")

    r = client.post(url, json=payload, headers={"X-Service-Api-Key": SERVICE_API_KEY})
    assert r.status_code == 200, r.text
    assert r.json()["risk_score"] == 0.3


def test_results_webhook_is_closed_when_no_key_is_configured(client, monkeypatch):
    # Sin clave configurada (o vacía) ni siquiera un header vacío pasa
    monkeypatch.setattr(settings, "JUMP_ANALYSIS_SERVICE_API_KEY", SecretStr(""))
    r = client.post(
        "/api/v1/jump-analyses/1/results",
        json={"risk_score": 0.3, "measurements": []},
        headers={"X-Service-Api-Key": ""},
    )
    assert r.status_code == 401
