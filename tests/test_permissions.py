"""Auditoría de permisos por rol (Fase 4): cada endpoint verifica el rol en el backend, no en la UI."""
from app.models.user import UserRole
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile

PROFILE = {"gender": "male", "height_cm": 178, "weight_kg": 72, "birth_date": "1998-05-20"}
MANAGED = {**PROFILE, "full_name": "Lucía Gómez"}


def _admin(register_and_verify, set_role, email: str) -> str:
    token = register_and_verify(email)
    set_role(email, UserRole.ADMIN)
    return token


def _user_id(client, token: str) -> int:
    return client.get("/api/v1/auth/me", headers=_auth_headers(token)).json()["id"]


def test_direct_user_creation_is_admin_only(client, register_and_verify, set_role):
    payload = {"email": "created@kinesiapp.com", "password": "Abcd1234!", "full_name": "Ana"}
    assert client.post("/api/v1/users", json=payload).status_code in (401, 403)
    athlete = register_and_verify("not-admin@kinesiapp.com")
    assert client.post("/api/v1/users", json=payload, headers=_auth_headers(athlete)).status_code == 403

    admin = _admin(register_and_verify, set_role, "creator@kinesiapp.com")
    r = client.post("/api/v1/users", json=payload, headers=_auth_headers(admin))
    assert r.status_code == 201, r.text
    assert r.json()["is_verified"] is False  # su dueño la verifica con el código al iniciar sesión
    assert client.post("/api/v1/users", json=payload, headers=_auth_headers(admin)).status_code == 409


def test_athlete_profile_reads_are_restricted(client, register_and_verify, set_role):
    owner = register_and_verify("bio-owner@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, owner)
    stranger = register_and_verify("bio-stranger@kinesiapp.com")
    coach = register_and_verify("bio-coach@kinesiapp.com", role="coach")
    admin = _admin(register_and_verify, set_role, "bio-admin@kinesiapp.com")

    assert client.get(f"/api/v1/athletes/{athlete_id}").status_code in (401, 403)
    assert client.get(f"/api/v1/athletes/{athlete_id}", headers=_auth_headers(stranger)).status_code == 404
    assert client.get(f"/api/v1/athletes/{athlete_id}", headers=_auth_headers(coach)).status_code == 404
    assert client.get(f"/api/v1/athletes/{athlete_id}", headers=_auth_headers(owner)).status_code == 200
    assert client.get(f"/api/v1/athletes/{athlete_id}", headers=_auth_headers(admin)).status_code == 200
    client.patch(f"/api/v1/athletes/{athlete_id}/coach", json={"coach_id": _user_id(client, coach)}, headers=_auth_headers(admin))
    assert client.get(f"/api/v1/athletes/{athlete_id}", headers=_auth_headers(coach)).status_code == 200


def test_administrative_profile_creation_is_admin_only_and_for_athletes(client, register_and_verify, set_role):
    athlete = register_and_verify("no-profile@kinesiapp.com")
    coach = register_and_verify("coach-noprofile@kinesiapp.com", role="coach")
    admin = _admin(register_and_verify, set_role, "profile-admin@kinesiapp.com")
    body = {**PROFILE, "user_id": _user_id(client, athlete)}

    assert client.post("/api/v1/athletes", json=body).status_code in (401, 403)
    assert client.post("/api/v1/athletes", json=body, headers=_auth_headers(athlete)).status_code == 403
    r = client.post("/api/v1/athletes", json={**body, "user_id": _user_id(client, coach)}, headers=_auth_headers(admin))
    assert r.json()["code"] == "invalid_role_assignment"
    assert client.post("/api/v1/athletes", json=body, headers=_auth_headers(admin)).status_code == 201


def test_admin_does_not_upload_nor_chat(client, register_and_verify, set_role, grant_consent, upload_jump, fake_llm):
    owner = register_and_verify("admin-target@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, owner)
    admin = _admin(register_and_verify, set_role, "no-upload-admin@kinesiapp.com")

    assert upload_jump(admin, athlete_id).status_code == 403
    r = client.post("/api/v1/jump-analyses/upload-token", json={"athlete_id": athlete_id}, headers=_auth_headers(admin))
    assert r.status_code == 403
    assert client.post("/api/v1/users/me/video-consent", json={"version": 1}, headers=_auth_headers(admin)).status_code == 403

    grant_consent(owner)
    analysis_id = upload_jump(owner, athlete_id).json()["id"]
    # Lectura de supervisión sí; conversar con el asistente no
    assert client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(admin)).status_code == 200
    chat_url = f"/api/v1/jump-analyses/{analysis_id}/chat/messages"
    assert client.get(chat_url, headers=_auth_headers(admin)).status_code == 403


def test_coach_reads_but_cannot_delete_recordings_of_account_athletes(
    client, register_and_verify, set_role, grant_consent, upload_jump
):
    owner = register_and_verify("account-owner@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, owner)
    coach = register_and_verify("readonly-coach@kinesiapp.com", role="coach")
    admin = _admin(register_and_verify, set_role, "assign-admin@kinesiapp.com")
    client.patch(f"/api/v1/athletes/{athlete_id}/coach", json={"coach_id": _user_id(client, coach)}, headers=_auth_headers(admin))
    grant_consent(owner)
    analysis_id = upload_jump(owner, athlete_id).json()["id"]

    assert client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(coach)).status_code == 200
    assert client.delete(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(coach)).status_code == 403

    # Las de su deportista gestionado sí las borra
    grant_consent(coach)
    managed = client.post("/api/v1/coach/athletes", json=MANAGED, headers=_auth_headers(coach)).json()["id"]
    managed_analysis = upload_jump(coach, managed).json()["id"]
    assert client.delete(f"/api/v1/jump-analyses/{managed_analysis}", headers=_auth_headers(coach)).status_code == 204
    # El admin puede borrar como moderación
    assert client.delete(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(admin)).status_code == 204


def test_admin_cannot_change_own_role_nor_orphan_managed_athletes(client, register_and_verify, set_role):
    admin = _admin(register_and_verify, set_role, "self-admin@kinesiapp.com")
    coach = register_and_verify("busy-coach@kinesiapp.com", role="coach")
    client.post("/api/v1/coach/athletes", json=MANAGED, headers=_auth_headers(coach))

    r = client.patch(f"/api/v1/users/{_user_id(client, admin)}/role", json={"role": "athlete"}, headers=_auth_headers(admin))
    assert (r.status_code, r.json()["code"]) == (403, "cannot_modify_own_account")
    r = client.patch(f"/api/v1/users/{_user_id(client, coach)}/role", json={"role": "athlete"}, headers=_auth_headers(admin))
    assert (r.status_code, r.json()["code"]) == (409, "coach_has_athletes")
    athlete = register_and_verify("promoted@kinesiapp.com")
    r = client.patch(f"/api/v1/users/{_user_id(client, athlete)}/role", json={"role": "coach"}, headers=_auth_headers(admin))
    assert r.json()["role"] == "coach"


def test_admin_deactivates_accounts_and_they_lose_their_session(client, register_and_verify, set_role):
    admin = _admin(register_and_verify, set_role, "status-admin@kinesiapp.com")
    athlete = register_and_verify("deactivated@kinesiapp.com")
    athlete_id = _user_id(client, athlete)
    login = client.post("/api/v1/auth/login", json={"email": "deactivated@kinesiapp.com", "password": "Supersecret1!"}).json()

    assert client.patch(f"/api/v1/users/{athlete_id}/status", json={"is_active": False}, headers=_auth_headers(athlete)).status_code == 403
    r = client.patch(f"/api/v1/users/{athlete_id}/status", json={"is_active": False}, headers=_auth_headers(admin))
    assert r.json()["is_active"] is False
    assert client.get("/api/v1/auth/me", headers=_auth_headers(athlete)).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 401
    assert client.patch(
        f"/api/v1/users/{_user_id(client, admin)}/status", json={"is_active": False}, headers=_auth_headers(admin)
    ).json()["code"] == "cannot_modify_own_account"

    client.patch(f"/api/v1/users/{athlete_id}/status", json={"is_active": True}, headers=_auth_headers(admin))
    assert client.post("/api/v1/auth/login", json={"email": "deactivated@kinesiapp.com", "password": "Supersecret1!"}).status_code == 200


def test_athlete_cannot_reach_other_roles_endpoints(client, register_and_verify):
    athlete = register_and_verify("plain-athlete@kinesiapp.com")
    headers = _auth_headers(athlete)
    for method, path in (
        ("get", "/api/v1/users"),
        ("get", "/api/v1/athletes"),
        ("get", "/api/v1/athletes/coached"),
        ("get", "/api/v1/coach/athletes"),
        ("post", "/api/v1/coach/athletes"),
        ("get", "/api/v1/jump-analyses/team"),
        ("get", "/api/v1/teams"),
        ("patch", "/api/v1/athletes/1/coach"),
        ("patch", "/api/v1/users/1/role"),
    ):
        assert getattr(client, method)(path, headers=headers, **({"json": {}} if method != "get" else {})).status_code == 403, path
