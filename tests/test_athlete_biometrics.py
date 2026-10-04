"""Ficha biométrica: validación de la fecha de nacimiento, edición parcial y edad derivada."""
from datetime import date

from app.core.config import settings
from app.core.time_utils import age_on
from tests.test_jump_analysis_rbac import _auth_headers

PROFILE = {"gender": "female", "height_cm": 165, "weight_kg": 58, "birth_date": "2004-05-10"}


def _years_ago(years: int, today: date | None = None) -> str:
    today = today or date.today()
    # 28 de febrero siempre existe: evita fechas inválidas al restar años a un 29
    return date(today.year - years, today.month, min(today.day, 28)).isoformat()


def test_age_is_derived_from_birth_date():
    assert age_on(date(2000, 6, 15), date(2026, 6, 14)) == 25
    assert age_on(date(2000, 6, 15), date(2026, 6, 15)) == 26
    assert age_on(date(2000, 2, 29), date(2026, 2, 28)) == 25


def test_profile_response_carries_birth_date_not_age(client, register_and_verify):
    token = register_and_verify("onboarding@kinesiapp.com")
    assert client.get("/api/v1/athletes/me", headers=_auth_headers(token)).status_code == 404

    r = client.post("/api/v1/athletes/me", json=PROFILE, headers=_auth_headers(token))
    assert r.status_code == 201, r.text
    assert client.get("/api/v1/athletes/me", headers=_auth_headers(token)).json()["birth_date"] == PROFILE["birth_date"]
    # La edad nunca viaja ni se guarda: sólo la fecha
    assert "age" not in r.json()


def test_birth_date_must_be_plausible(client, register_and_verify):
    token = register_and_verify("birth@kinesiapp.com")
    for invalid in (
        date.today().isoformat(),
        "2999-01-01",
        _years_ago(settings.ATHLETE_MIN_AGE_YEARS - 1),
        _years_ago(settings.ATHLETE_MAX_AGE_YEARS + 1),
    ):
        r = client.post("/api/v1/athletes/me", json={**PROFILE, "birth_date": invalid}, headers=_auth_headers(token))
        assert r.status_code == 422, invalid


def test_athlete_edits_biometrics_partially(client, register_and_verify):
    token = register_and_verify("edit-bio@kinesiapp.com")
    client.post("/api/v1/athletes/me", json=PROFILE, headers=_auth_headers(token))

    r = client.patch("/api/v1/athletes/me", json={"weight_kg": 60.5, "birth_date": "2003-01-02"}, headers=_auth_headers(token))
    assert r.status_code == 200, r.text
    assert (r.json()["weight_kg"], r.json()["birth_date"], r.json()["height_cm"]) == (60.5, "2003-01-02", 165)
    assert client.patch(
        "/api/v1/athletes/me", json={"birth_date": "2999-01-01"}, headers=_auth_headers(token)
    ).status_code == 422
