"""Datos del informe en PDF: el nombre del entrenador responsable viaja con la ficha del deportista."""
from app.models.user import UserRole
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile

MANAGED = {"full_name": "Lucía Gómez", "gender": "female", "height_cm": 160, "weight_kg": 55, "birth_date": "2008-04-01"}


def test_athlete_profile_carries_the_responsible_coach_name(client, register_and_verify, set_role):
    athlete = register_and_verify("report-athlete@kinesiapp.com")
    _create_athlete_profile(client, athlete)
    assert client.get("/api/v1/athletes/me", headers=_auth_headers(athlete)).json()["coach_name"] is None

    coach = register_and_verify("report-coach@kinesiapp.com", role="coach")
    admin = register_and_verify("report-admin@kinesiapp.com")
    set_role("report-admin@kinesiapp.com", UserRole.ADMIN)
    me = client.get("/api/v1/athletes/me", headers=_auth_headers(athlete)).json()
    coach_id = client.get("/api/v1/auth/me", headers=_auth_headers(coach)).json()["id"]
    client.patch(f"/api/v1/athletes/{me['id']}/coach", json={"coach_id": coach_id}, headers=_auth_headers(admin))

    assert client.get("/api/v1/athletes/me", headers=_auth_headers(athlete)).json()["coach_name"] == "Test User"
    managed = client.post("/api/v1/coach/athletes", json=MANAGED, headers=_auth_headers(coach)).json()
    assert managed["coach_name"] == "Test User"
