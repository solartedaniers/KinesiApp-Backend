"""Recuperación en 3 pasos, cambio de contraseña, política de contraseñas, perfil y avatares."""
import base64
import re

from app.models.user import User

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_AVATAR = {"content_type": "image/png", "data_base64": base64.b64encode(PNG_BYTES).decode()}
PROFILE = {"gender": "male", "height_cm": 175, "weight_kg": 70, "birth_date": "2000-01-01"}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request_reset_code(client, email_outbox, email: str) -> str:
    assert client.post("/api/v1/auth/password-recovery/request", json={"email": email}).status_code == 202
    message = next(item for item in reversed(email_outbox) if item["to"] == email)
    return re.search(r"\b\d{6}\b", message["body"]).group()


def test_register_rejects_password_without_digit(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@kinesiapp.com", "password": "onlyletters", "full_name": "Weak"},
    )
    assert r.status_code == 422


def test_recovery_verify_step_does_not_consume_code(client, register_and_verify, email_outbox):
    register_and_verify("steps@kinesiapp.com")
    code = _request_reset_code(client, email_outbox, "steps@kinesiapp.com")

    wrong = "000000" if code != "000000" else "111111"
    r = client.post("/api/v1/auth/password-recovery/verify", json={"email": "steps@kinesiapp.com", "code": wrong})
    assert r.json()["code"] == "invalid_otp"
    r = client.post("/api/v1/auth/password-recovery/verify", json={"email": "steps@kinesiapp.com", "code": code})
    assert r.status_code == 204

    r = client.post(
        "/api/v1/auth/password-recovery/confirm",
        json={"email": "steps@kinesiapp.com", "code": code, "new_password": "brandnew123"},
    )
    assert r.status_code == 204


def test_recovery_verify_unknown_email_looks_like_wrong_code(client):
    r = client.post("/api/v1/auth/password-recovery/verify", json={"email": "ghost@kinesiapp.com", "code": "123456"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_otp"


def test_recovery_rejects_current_password(client, register_and_verify, email_outbox):
    register_and_verify("reuse@kinesiapp.com")
    code = _request_reset_code(client, email_outbox, "reuse@kinesiapp.com")
    r = client.post(
        "/api/v1/auth/password-recovery/confirm",
        json={"email": "reuse@kinesiapp.com", "code": code, "new_password": "supersecret1"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "password_reused"


def test_change_password_flow(client, register_and_verify, db_session):
    token = register_and_verify("change@kinesiapp.com")

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "wrongpass1", "new_password": "another123"},
        headers=_auth(token),
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_current_password"

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "supersecret1", "new_password": "supersecret1"},
        headers=_auth(token),
    )
    assert r.json()["code"] == "password_reused"

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "supersecret1", "new_password": "another123"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["refresh_token"]

    stored = db_session.query(User).filter(User.email == "change@kinesiapp.com").one()
    assert stored.hashed_password.startswith("$2") and "another123" not in stored.hashed_password
    assert client.post("/api/v1/auth/login", json={"email": "change@kinesiapp.com", "password": "another123"}).status_code == 200


def test_update_profile_and_avatar(client, register_and_verify):
    token = register_and_verify("me@kinesiapp.com")

    r = client.patch("/api/v1/users/me", json={"full_name": "Nuevo Nombre"}, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["full_name"] == "Nuevo Nombre"

    r = client.put("/api/v1/users/me/avatar", json=PNG_AVATAR, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["avatar_data_url"].startswith("data:image/png;base64,")

    r = client.delete("/api/v1/users/me/avatar", headers=_auth(token))
    assert r.json()["avatar_data_url"] is None


def test_avatar_rejects_mismatched_content(client, register_and_verify):
    token = register_and_verify("fake@kinesiapp.com")
    r = client.put(
        "/api/v1/users/me/avatar",
        json={"content_type": "image/jpeg", "data_base64": PNG_AVATAR["data_base64"]},
        headers=_auth(token),
    )
    assert r.status_code == 422
    r = client.put(
        "/api/v1/users/me/avatar",
        json={"content_type": "image/png", "data_base64": "not base64!"},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_coach_sets_managed_athlete_avatar_and_team_analyses(client, register_and_verify, grant_consent, upload_jump):
    coach = register_and_verify("avatar-coach@kinesiapp.com", role="coach")
    other = register_and_verify("other-coach@kinesiapp.com", role="coach")
    athlete = client.post(
        "/api/v1/coach/athletes", json={**PROFILE, "full_name": "Ana"}, headers=_auth(coach)
    ).json()

    r = client.put(f"/api/v1/coach/athletes/{athlete['id']}/avatar", json=PNG_AVATAR, headers=_auth(coach))
    assert r.status_code == 200
    assert r.json()["display_avatar"].startswith("data:image/png")
    assert client.put(
        f"/api/v1/coach/athletes/{athlete['id']}/avatar", json=PNG_AVATAR, headers=_auth(other)
    ).status_code == 404

    grant_consent(coach)
    assert upload_jump(coach, athlete["id"]).status_code == 202
    team = client.get("/api/v1/jump-analyses/team", headers=_auth(coach)).json()
    assert [item["athlete_id"] for item in team] == [athlete["id"]]
    assert client.get("/api/v1/jump-analyses/team", headers=_auth(other)).json() == []
