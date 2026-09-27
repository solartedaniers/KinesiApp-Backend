"""Reproducción del video subido (token de corta vida) y tipo de movimiento del análisis."""
from app.core.security import create_access_token, create_video_access_token
from tests.conftest import VIDEO_BYTES
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile


def _uploaded_analysis(client, register_and_verify, grant_consent, upload_jump, email, **kwargs):
    token = register_and_verify(email)
    athlete_id = _create_athlete_profile(client, token)
    grant_consent(token)
    r = upload_jump(token, athlete_id, **kwargs)
    assert r.status_code == 202, r.text
    return token, r.json()


def test_owner_streams_own_video_with_range_support(client, register_and_verify, grant_consent, upload_jump):
    token, analysis = _uploaded_analysis(client, register_and_verify, grant_consent, upload_jump, "play@kinesiapp.com")

    r = client.get(f"/api/v1/jump-analyses/{analysis['id']}/video-access", headers=_auth_headers(token))
    assert r.status_code == 200, r.text
    video_url = f"/api/v1/jump-analyses/{analysis['id']}/video?token={r.json()['token']}"

    r = client.get(video_url)
    assert r.status_code == 200
    assert r.content == VIDEO_BYTES
    assert r.headers["content-type"].startswith("video/")

    # Los reproductores piden por rangos para poder adelantar
    r = client.get(video_url, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.content == VIDEO_BYTES[10:20]


def test_video_access_follows_analysis_permissions(client, register_and_verify, grant_consent, upload_jump):
    _, analysis = _uploaded_analysis(client, register_and_verify, grant_consent, upload_jump, "owner-v@kinesiapp.com")
    intruder = register_and_verify("intruder-v@kinesiapp.com")

    r = client.get(f"/api/v1/jump-analyses/{analysis['id']}/video-access", headers=_auth_headers(intruder))
    assert r.status_code == 403


def test_video_endpoint_rejects_foreign_or_wrong_tokens(client, register_and_verify, grant_consent, upload_jump):
    token, analysis = _uploaded_analysis(client, register_and_verify, grant_consent, upload_jump, "tokens@kinesiapp.com")
    url = f"/api/v1/jump-analyses/{analysis['id']}/video"

    assert client.get(url).status_code == 422  # sin token
    # Token de video de otro análisis, o un access token de usuario: no abren este video
    other_video_token, _ = create_video_access_token(analysis["id"] + 1)
    for bad in (other_video_token, create_access_token(1), "garbage"):
        assert client.get(url, params={"token": bad}).status_code == 401
    # Y al revés: el token de video no sirve como sesión de usuario
    video_token, _ = create_video_access_token(analysis["id"])
    assert client.get("/api/v1/auth/me", headers=_auth_headers(video_token)).status_code == 401


def test_movement_type_is_stored_and_defaults_to_jump(client, register_and_verify, grant_consent, upload_jump):
    token, jump = _uploaded_analysis(client, register_and_verify, grant_consent, upload_jump, "mov@kinesiapp.com")
    assert jump["movement_type"] == "jump"

    r = upload_jump(token, jump["athlete_id"], movement_type="squat")
    assert r.status_code == 202, r.text
    squat_id = r.json()["id"]
    assert r.json()["movement_type"] == "squat"

    # Mismo procesamiento de demostración sin importar el tipo
    squat = client.get(f"/api/v1/jump-analyses/{squat_id}", headers=_auth_headers(token)).json()
    processed_jump = client.get(f"/api/v1/jump-analyses/{jump['id']}", headers=_auth_headers(token)).json()
    assert (squat["movement_type"], squat["status"]) == ("squat", "processed")
    assert squat["risk_score"] == processed_jump["risk_score"]

    assert upload_jump(token, jump["athlete_id"], movement_type="dance").status_code == 422
