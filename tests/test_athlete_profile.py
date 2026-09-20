"""Pruebas del perfil de deportista atado al usuario autenticado (/athletes/me)."""
from app.models.user import User


def _register_and_get_access_token(client, db_session, email: str) -> str:
    # Flujo real: registrar, leer el OTP directo de la DB (no hay SMTP en tests) y verificar
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1", "full_name": "Atleta"},
    )
    assert r.status_code == 201, r.text

    user = db_session.query(User).filter(User.email == email).one()
    r = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": user.verification_code}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_and_get_own_profile(client, db_session):
    token = _register_and_get_access_token(client, db_session, "runner@kinesiapp.com")

    r = client.get("/api/v1/athletes/me", headers=_auth_headers(token))
    assert r.status_code == 404, "todavía no existe perfil para este usuario"

    payload = {"sport": "running", "height_cm": 178, "weight_kg": 72, "birth_date": "1998-05-20"}
    r = client.post("/api/v1/athletes/me", json=payload, headers=_auth_headers(token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sport"] == "running"

    r = client.get("/api/v1/athletes/me", headers=_auth_headers(token))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == body["id"]


def test_cannot_create_two_profiles_for_same_user(client, db_session):
    token = _register_and_get_access_token(client, db_session, "duplicado@kinesiapp.com")
    payload = {"sport": "swimming", "height_cm": 165, "weight_kg": 58, "birth_date": "2001-02-10"}

    r = client.post("/api/v1/athletes/me", json=payload, headers=_auth_headers(token))
    assert r.status_code == 201

    r = client.post("/api/v1/athletes/me", json=payload, headers=_auth_headers(token))
    assert r.status_code == 409


def test_athlete_me_requires_authentication(client):
    r = client.get("/api/v1/athletes/me")
    assert r.status_code in (401, 403)  # HTTPBearer sin header devuelve 403; sin scheme válido, 401

    r = client.post(
        "/api/v1/athletes/me",
        json={"sport": "running", "height_cm": 170, "weight_kg": 65, "birth_date": "2000-01-01"},
    )
    assert r.status_code in (401, 403)
