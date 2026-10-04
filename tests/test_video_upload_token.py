"""Subida desde el navegador con un token de subida de vida corta, acotado a un deportista."""
from app.core.config import settings
from tests.conftest import VIDEO_BYTES
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile

MANAGED = {"full_name": "Lucía Gómez", "gender": "female", "height_cm": 160, "weight_kg": 55, "birth_date": "2008-04-01"}


def _token(client, access_token: str, athlete_id: int):
    return client.post("/api/v1/jump-analyses/upload-token", json={"athlete_id": athlete_id}, headers=_auth_headers(access_token))


def _upload_with(client, upload_token: str, athlete_id: int):
    return client.post(
        "/api/v1/jump-analyses/upload",
        data={"athlete_id": str(athlete_id), "movement_type": "squat"},
        files={"video": ("squat.mp4", VIDEO_BYTES, "video/mp4")},
        headers=_auth_headers(upload_token),
    )


def test_athlete_uploads_with_an_upload_token(client, register_and_verify, grant_consent):
    access = register_and_verify("token-up@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, access)
    grant_consent(access)

    r = _token(client, access, athlete_id)
    assert r.status_code == 200, r.text
    r = _upload_with(client, r.json()["token"], athlete_id)
    assert r.status_code == 202, r.text
    assert r.json()["movement_type"] == "squat"


def test_upload_token_is_scoped_to_one_athlete_and_is_not_a_session(
    client, register_and_verify, grant_consent
):
    coach = register_and_verify("token-coach@kinesiapp.com", role="coach")
    grant_consent(coach)
    first = client.post("/api/v1/coach/athletes", json=MANAGED, headers=_auth_headers(coach)).json()["id"]
    second = client.post("/api/v1/coach/athletes", json={**MANAGED, "full_name": "Pedro Ruiz"}, headers=_auth_headers(coach)).json()["id"]

    upload_token = _token(client, coach, first).json()["token"]
    assert _upload_with(client, upload_token, second).status_code == 403
    assert _upload_with(client, upload_token, first).status_code == 202
    # No abre ninguna otra operación de la cuenta
    assert client.get("/api/v1/auth/me", headers=_auth_headers(upload_token)).status_code == 401
    assert client.get("/api/v1/coach/athletes", headers=_auth_headers(upload_token)).status_code == 401


def test_upload_token_applies_the_upload_rules_up_front(client, register_and_verify, grant_consent):
    owner = register_and_verify("token-owner@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, owner)
    # Sin consentimiento vigente
    assert (_token(client, owner, athlete_id).json()["code"]) == "consent_required"
    # Ni otro deportista ni un athlete_id inexistente
    intruder = register_and_verify("token-intruder@kinesiapp.com")
    _create_athlete_profile(client, intruder)
    grant_consent(intruder)
    assert _token(client, intruder, athlete_id).status_code == 403
    assert _token(client, owner, 99999).status_code == 404


def test_public_video_limits_match_the_api(client):
    assert client.get("/api/v1/public/video-limits").json() == {"max_size_bytes": settings.MAX_VIDEO_UPLOAD_BYTES}


def test_managed_athlete_name_only_letters(client, register_and_verify):
    coach = register_and_verify("name-coach@kinesiapp.com", role="coach")
    r = client.post("/api/v1/coach/athletes", json={**MANAGED, "full_name": "Lucía 2"}, headers=_auth_headers(coach))
    assert r.status_code == 422
    athlete_id = client.post("/api/v1/coach/athletes", json=MANAGED, headers=_auth_headers(coach)).json()["id"]
    r = client.patch(f"/api/v1/coach/athletes/{athlete_id}", json={"full_name": "R2-D2"}, headers=_auth_headers(coach))
    assert r.status_code == 422
