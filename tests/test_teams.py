"""Equipos: el coach agrupa a sus deportistas (con cuenta o gestionados); el admin administra todos."""
from app.models.user import UserRole
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile

MANAGED = {"full_name": "Lucía Gómez", "gender": "female", "height_cm": 160, "weight_kg": 55, "birth_date": "2008-04-01"}


def _managed(client, coach_token: str, name: str = "Lucía Gómez") -> int:
    r = client.post("/api/v1/coach/athletes", json={**MANAGED, "full_name": name}, headers=_auth_headers(coach_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _team(client, token: str, name: str):
    return client.post("/api/v1/teams", json={"name": name}, headers=_auth_headers(token))


def _admin(register_and_verify, set_role, email: str) -> str:
    token = register_and_verify(email)
    set_role(email, UserRole.ADMIN)
    return token


def test_coach_creates_team_and_assigns_own_athletes(client, register_and_verify, set_role, db_session):
    coach = register_and_verify("team-coach@kinesiapp.com", role="coach")
    managed = _managed(client, coach)
    # Deportista con cuenta asignado por un admin a este coach
    athlete = register_and_verify("team-athlete@kinesiapp.com")
    account_athlete = _create_athlete_profile(client, athlete)
    admin = _admin(register_and_verify, set_role, "team-admin@kinesiapp.com")
    coach_id = client.get("/api/v1/auth/me", headers=_auth_headers(coach)).json()["id"]
    client.patch(f"/api/v1/athletes/{account_athlete}/coach", json={"coach_id": coach_id}, headers=_auth_headers(admin))

    r = _team(client, coach, "  Sub 17 ")
    assert r.status_code == 201, r.text
    team = r.json()
    assert (team["name"], team["athlete_ids"]) == ("Sub 17", [])

    for athlete_id in (managed, account_athlete, managed):  # agregar dos veces no duplica
        r = client.put(f"/api/v1/teams/{team['id']}/athletes/{athlete_id}", headers=_auth_headers(coach))
        assert r.status_code == 200, r.text
    assert r.json()["athlete_ids"] == sorted([managed, account_athlete])

    r = client.delete(f"/api/v1/teams/{team['id']}/athletes/{managed}", headers=_auth_headers(coach))
    assert r.json()["athlete_ids"] == [account_athlete]
    assert [t["name"] for t in client.get("/api/v1/teams", headers=_auth_headers(coach)).json()] == ["Sub 17"]


def test_team_names_are_unique_per_owner(client, register_and_verify):
    coach = register_and_verify("dup-team@kinesiapp.com", role="coach")
    other = register_and_verify("dup-team2@kinesiapp.com", role="coach")
    assert _team(client, coach, "Delanteros").status_code == 201
    assert _team(client, coach, "Delanteros").json()["code"] == "team_name_taken"
    assert _team(client, other, "Delanteros").status_code == 201
    second = _team(client, coach, "Defensas").json()["id"]
    r = client.patch(f"/api/v1/teams/{second}", json={"name": "Delanteros"}, headers=_auth_headers(coach))
    assert r.json()["code"] == "team_name_taken"


def test_coach_cannot_add_other_coaches_athletes_nor_see_their_teams(client, register_and_verify):
    coach = register_and_verify("own-coach@kinesiapp.com", role="coach")
    stranger = register_and_verify("stranger-coach@kinesiapp.com", role="coach")
    foreign_athlete = _managed(client, stranger, "Pedro Ruiz")
    foreign_team = _team(client, stranger, "Ajeno").json()["id"]
    team = _team(client, coach, "Propio").json()["id"]

    r = client.put(f"/api/v1/teams/{team}/athletes/{foreign_athlete}", headers=_auth_headers(coach))
    assert (r.status_code, r.json()["code"]) == (400, "invalid_team_member")
    for method, path in (
        ("get", f"/api/v1/teams/{foreign_team}"),
        ("patch", f"/api/v1/teams/{foreign_team}"),
        ("delete", f"/api/v1/teams/{foreign_team}"),
        ("put", f"/api/v1/teams/{foreign_team}/athletes/{foreign_athlete}"),
    ):
        kwargs = {"json": {"name": "x"}} if method == "patch" else {}
        assert getattr(client, method)(path, headers=_auth_headers(coach), **kwargs).status_code == 404, path


def test_athletes_cannot_manage_teams(client, register_and_verify):
    athlete = register_and_verify("no-teams@kinesiapp.com")
    assert client.get("/api/v1/teams", headers=_auth_headers(athlete)).status_code == 403
    assert _team(client, athlete, "Mío").status_code == 403


def test_admin_manages_every_team_and_groups_any_athlete(client, register_and_verify, set_role):
    admin = _admin(register_and_verify, set_role, "teams-admin@kinesiapp.com")
    coach = register_and_verify("teams-coach@kinesiapp.com", role="coach")
    coach_team = _team(client, coach, "Del coach").json()["id"]
    managed = _managed(client, coach)
    athlete = _create_athlete_profile(client, register_and_verify("free-athlete@kinesiapp.com"))

    admin_team = _team(client, admin, "Selección").json()["id"]
    assert client.put(f"/api/v1/teams/{admin_team}/athletes/{athlete}", headers=_auth_headers(admin)).status_code == 200
    assert {t["id"] for t in client.get("/api/v1/teams", headers=_auth_headers(admin)).json()} == {coach_team, admin_team}
    # En el equipo de un coach sólo entran sus deportistas, aunque lo edite un admin
    r = client.put(f"/api/v1/teams/{coach_team}/athletes/{athlete}", headers=_auth_headers(admin))
    assert r.json()["code"] == "invalid_team_member"
    assert client.put(f"/api/v1/teams/{coach_team}/athletes/{managed}", headers=_auth_headers(admin)).status_code == 200


def test_reassigning_coach_removes_athlete_from_previous_coach_teams(client, register_and_verify, set_role):
    admin = _admin(register_and_verify, set_role, "move-admin@kinesiapp.com")
    first = register_and_verify("first-coach@kinesiapp.com", role="coach")
    second = register_and_verify("second-coach@kinesiapp.com", role="coach")
    first_id = client.get("/api/v1/auth/me", headers=_auth_headers(first)).json()["id"]
    second_id = client.get("/api/v1/auth/me", headers=_auth_headers(second)).json()["id"]
    athlete = _create_athlete_profile(client, register_and_verify("moving@kinesiapp.com"))
    client.patch(f"/api/v1/athletes/{athlete}/coach", json={"coach_id": first_id}, headers=_auth_headers(admin))
    first_team = _team(client, first, "Primero").json()["id"]
    admin_team = _team(client, admin, "Selección").json()["id"]
    client.put(f"/api/v1/teams/{first_team}/athletes/{athlete}", headers=_auth_headers(first))
    client.put(f"/api/v1/teams/{admin_team}/athletes/{athlete}", headers=_auth_headers(admin))

    client.patch(f"/api/v1/athletes/{athlete}/coach", json={"coach_id": second_id}, headers=_auth_headers(admin))
    assert client.get(f"/api/v1/teams/{first_team}", headers=_auth_headers(first)).json()["athlete_ids"] == []
    assert client.get(f"/api/v1/teams/{admin_team}", headers=_auth_headers(admin)).json()["athlete_ids"] == [athlete]


def test_deleting_team_or_athlete_keeps_the_rest(client, register_and_verify):
    coach = register_and_verify("cleanup-coach@kinesiapp.com", role="coach")
    kept, removed = _managed(client, coach, "Ana Pérez"), _managed(client, coach, "Luis Díaz")
    team = _team(client, coach, "Grupo").json()["id"]
    for athlete_id in (kept, removed):
        client.put(f"/api/v1/teams/{team}/athletes/{athlete_id}", headers=_auth_headers(coach))

    client.delete(f"/api/v1/coach/athletes/{removed}", headers=_auth_headers(coach))
    assert client.get(f"/api/v1/teams/{team}", headers=_auth_headers(coach)).json()["athlete_ids"] == [kept]
    assert client.delete(f"/api/v1/teams/{team}", headers=_auth_headers(coach)).status_code == 204
    assert len(client.get("/api/v1/coach/athletes", headers=_auth_headers(coach)).json()) == 1
