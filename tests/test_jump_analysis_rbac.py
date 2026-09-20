"""RBAC de análisis de saltos: deportista (dueño), coach (asignado) y admin (todo)."""
from app.models.user import UserRole


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_id(client, token: str) -> int:
    return client.get("/api/v1/auth/me", headers=_auth_headers(token)).json()["id"]


def _create_athlete_profile(client, token: str, sport: str = "running") -> int:
    r = client.post(
        "/api/v1/athletes/me",
        json={"sport": sport, "height_cm": 170, "weight_kg": 65, "birth_date": "2000-01-01"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_athlete_creates_and_owns_analysis(client, register_and_verify):
    token = register_and_verify("owner@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, token)

    r = client.post(
        "/api/v1/jump-analyses",
        json={"athlete_id": athlete_id, "video_reference": "s3://video.mp4"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 201, r.text

    analysis_id = r.json()["id"]
    r = client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(token))
    assert r.status_code == 200, r.text


def test_other_athlete_cannot_access_analysis(client, register_and_verify):
    owner_token = register_and_verify("owner2@kinesiapp.com")
    owner_athlete_id = _create_athlete_profile(client, owner_token)
    r = client.post(
        "/api/v1/jump-analyses",
        json={"athlete_id": owner_athlete_id, "video_reference": "s3://video.mp4"},
        headers=_auth_headers(owner_token),
    )
    analysis_id = r.json()["id"]

    intruder_token = register_and_verify("intruso@kinesiapp.com")
    _create_athlete_profile(client, intruder_token, sport="swimming")

    r = client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(intruder_token))
    assert r.status_code == 403

    # Tampoco puede crear un análisis para un athlete_id que no es el suyo
    r = client.post(
        "/api/v1/jump-analyses",
        json={"athlete_id": owner_athlete_id, "video_reference": "s3://otro.mp4"},
        headers=_auth_headers(intruder_token),
    )
    assert r.status_code == 403


def test_coach_can_view_assigned_athlete_but_not_create(client, register_and_verify, set_role):
    athlete_token = register_and_verify("deportista@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, athlete_token)
    r = client.post(
        "/api/v1/jump-analyses",
        json={"athlete_id": athlete_id, "video_reference": "s3://video.mp4"},
        headers=_auth_headers(athlete_token),
    )
    analysis_id = r.json()["id"]

    coach_token = register_and_verify("coach@kinesiapp.com")
    set_role("coach@kinesiapp.com", UserRole.COACH)
    coach_id = _user_id(client, coach_token)

    admin_token = register_and_verify("admin1@kinesiapp.com")
    set_role("admin1@kinesiapp.com", UserRole.ADMIN)

    # Antes de asignarlo, el coach no tiene acceso
    r = client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(coach_token))
    assert r.status_code == 403

    r = client.patch(
        f"/api/v1/athletes/{athlete_id}/coach",
        json={"coach_id": coach_id},
        headers=_auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text

    # Ya asignado, el coach puede consultar pero no crear análisis del deportista
    r = client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(coach_token))
    assert r.status_code == 200, r.text

    r = client.get(f"/api/v1/jump-analyses/by-athlete/{athlete_id}", headers=_auth_headers(coach_token))
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.post(
        "/api/v1/jump-analyses",
        json={"athlete_id": athlete_id, "video_reference": "s3://otro.mp4"},
        headers=_auth_headers(coach_token),
    )
    assert r.status_code == 403


def test_admin_has_full_access_and_manages_roles(client, register_and_verify, set_role):
    athlete_token = register_and_verify("otro-deportista@kinesiapp.com")
    athlete_id = _create_athlete_profile(client, athlete_token)
    r = client.post(
        "/api/v1/jump-analyses",
        json={"athlete_id": athlete_id, "video_reference": "s3://video.mp4"},
        headers=_auth_headers(athlete_token),
    )
    analysis_id = r.json()["id"]

    admin_token = register_and_verify("admin2@kinesiapp.com")
    set_role("admin2@kinesiapp.com", UserRole.ADMIN)

    # Admin ve cualquier análisis sin estar asignado como coach
    r = client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(admin_token))
    assert r.status_code == 200

    # Sólo admin puede listar usuarios o ascender roles
    r = client.get("/api/v1/users", headers=_auth_headers(athlete_token))
    assert r.status_code == 403
    r = client.get("/api/v1/users", headers=_auth_headers(admin_token))
    assert r.status_code == 200

    athlete_user_id = _user_id(client, athlete_token)
    r = client.patch(
        f"/api/v1/users/{athlete_user_id}/role",
        json={"role": "coach"},
        headers=_auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "coach"

    # Sólo admin puede asignar coaches
    r = client.patch(
        f"/api/v1/athletes/{athlete_id}/coach",
        json={"coach_id": athlete_user_id},
        headers=_auth_headers(athlete_token),
    )
    assert r.status_code == 403

    # Sólo admin puede listar todos los perfiles de deportista (pantalla de asignación de coach)
    r = client.get("/api/v1/athletes", headers=_auth_headers(athlete_token))
    assert r.status_code == 403
    r = client.get("/api/v1/athletes", headers=_auth_headers(admin_token))
    assert r.status_code == 200
    assert any(profile["id"] == athlete_id for profile in r.json())
