"""Rol elegido en el registro, edición del propio perfil y CRUD de deportistas gestionados por un coach."""

PROFILE = {"gender": "male", "height_cm": 178, "weight_kg": 72, "birth_date": "1998-05-20"}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_as_coach_keeps_role_after_verification(client, register_and_verify):
    token = register_and_verify("coach@kinesiapp.com", role="coach")
    r = client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.json()["role"] == "coach"


def test_register_without_role_defaults_to_athlete(client, register_and_verify, email_outbox):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "legacy@kinesiapp.com", "password": "supersecret1", "full_name": "Legacy"},
    )
    assert r.status_code == 201
    assert r.json()["role"] == "athlete"


def test_register_rejects_admin_role(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "evil@kinesiapp.com", "password": "supersecret1", "full_name": "Evil", "role": "admin"},
    )
    assert r.status_code == 422


def test_athlete_can_update_own_profile(client, register_and_verify):
    token = register_and_verify("editor@kinesiapp.com")
    client.post("/api/v1/athletes/me", json=PROFILE, headers=_auth(token))

    r = client.patch("/api/v1/athletes/me", json={"weight_kg": 75.5, "gender": None}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["weight_kg"] == 75.5
    assert r.json()["gender"] == "male", "null explícito se ignora"
    assert r.json()["display_name"] == "Test User"


def test_coach_managed_athlete_crud(client, register_and_verify):
    coach = register_and_verify("crud-coach@kinesiapp.com", role="coach")

    r = client.post("/api/v1/coach/athletes", json={**PROFILE, "full_name": "Ana Pérez"}, headers=_auth(coach))
    assert r.status_code == 201, r.text
    athlete = r.json()
    assert athlete["is_managed"] is True and athlete["user_id"] is None
    assert athlete["display_name"] == "Ana Pérez"

    r = client.patch(f"/api/v1/coach/athletes/{athlete['id']}", json={"height_cm": 180}, headers=_auth(coach))
    assert r.status_code == 200 and r.json()["height_cm"] == 180

    r = client.get("/api/v1/coach/athletes", headers=_auth(coach))
    assert [a["id"] for a in r.json()] == [athlete["id"]]

    r = client.delete(f"/api/v1/coach/athletes/{athlete['id']}", headers=_auth(coach))
    assert r.status_code == 204
    assert client.get("/api/v1/coach/athletes", headers=_auth(coach)).json() == []


def test_coach_cannot_touch_other_coach_athletes(client, register_and_verify):
    owner = register_and_verify("owner-coach@kinesiapp.com", role="coach")
    intruder = register_and_verify("intruder-coach@kinesiapp.com", role="coach")
    athlete_id = client.post(
        "/api/v1/coach/athletes", json={**PROFILE, "full_name": "Luis"}, headers=_auth(owner)
    ).json()["id"]

    assert client.patch(f"/api/v1/coach/athletes/{athlete_id}", json={"height_cm": 1}, headers=_auth(intruder)).status_code == 404
    assert client.delete(f"/api/v1/coach/athletes/{athlete_id}", headers=_auth(intruder)).status_code == 404


def test_coach_cannot_delete_account_backed_athlete(client, register_and_verify, set_role, db_session):
    from app.models.athlete import AthleteProfile
    from app.models.user import User

    coach = register_and_verify("assigned-coach@kinesiapp.com", role="coach")
    athlete = register_and_verify("real-athlete@kinesiapp.com")
    profile_id = client.post("/api/v1/athletes/me", json=PROFILE, headers=_auth(athlete)).json()["id"]

    # Simula la asignación de un admin
    coach_id = db_session.query(User).filter(User.email == "assigned-coach@kinesiapp.com").one().id
    db_session.get(AthleteProfile, profile_id).coach_id = coach_id
    db_session.commit()

    assert len(client.get("/api/v1/coach/athletes", headers=_auth(coach)).json()) == 1
    assert client.delete(f"/api/v1/coach/athletes/{profile_id}", headers=_auth(coach)).status_code == 404


def test_athlete_cannot_use_coach_endpoints(client, register_and_verify):
    token = register_and_verify("sneaky@kinesiapp.com")
    r = client.post("/api/v1/coach/athletes", json={**PROFILE, "full_name": "X"}, headers=_auth(token))
    assert r.status_code == 403


def test_managed_athlete_is_linked_to_its_coach(client, register_and_verify):
    coach = register_and_verify("linked-coach@kinesiapp.com", role="coach")
    coach_id = client.get("/api/v1/auth/me", headers=_auth(coach)).json()["id"]

    created = client.post(
        "/api/v1/coach/athletes", json={**PROFILE, "full_name": "Sofía"}, headers=_auth(coach)
    ).json()
    assert created["coach_id"] == coach_id

    # Aparece de inmediato en los dos listados del coach, nunca como huérfano
    assert [a["id"] for a in client.get("/api/v1/coach/athletes", headers=_auth(coach)).json()] == [created["id"]]
    assert [a["id"] for a in client.get("/api/v1/athletes/coached", headers=_auth(coach)).json()] == [created["id"]]


def test_coach_records_and_lists_analyses_of_managed_athlete(client, register_and_verify, grant_consent, upload_jump):
    coach = register_and_verify("analyst-coach@kinesiapp.com", role="coach")
    athlete_id = client.post(
        "/api/v1/coach/athletes", json={**PROFILE, "full_name": "Mateo"}, headers=_auth(coach)
    ).json()["id"]

    # El coach sube por su deportista gestionado: el consentimiento exigido es el suyo
    grant_consent(coach)
    r = upload_jump(coach, athlete_id)
    assert r.status_code == 202, r.text
    r = client.get(f"/api/v1/jump-analyses/by-athlete/{athlete_id}", headers=_auth(coach))
    assert len(r.json()) == 1


def test_gender_is_required_and_validated(client, register_and_verify):
    token = register_and_verify("gender@kinesiapp.com")
    no_gender = {k: v for k, v in PROFILE.items() if k != "gender"}
    assert client.post("/api/v1/athletes/me", json=no_gender, headers=_auth(token)).status_code == 422
    assert client.post("/api/v1/athletes/me", json={**PROFILE, "gender": "x"}, headers=_auth(token)).status_code == 422
