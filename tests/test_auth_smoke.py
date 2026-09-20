"""Prueba de humo end-to-end del módulo de auth: registro -> OTP -> login -> refresh -> recuperación."""
from app.models.user import User


def _read_verification_code(db_session, email: str) -> str:
    # El código solo "llega" por email (que en test no hay SMTP real); se lee directo de la DB
    user = db_session.query(User).filter(User.email == email).one()
    return user.verification_code


def _read_reset_code(db_session, email: str) -> str:
    db_session.expire_all()
    user = db_session.query(User).filter(User.email == email).one()
    return user.password_reset_code


def test_register_verify_login_refresh_and_password_recovery(client, db_session):
    email = "atleta@kinesiapp.com"

    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1", "full_name": "Atleta Uno"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["is_verified"] is False

    # Login antes de verificar el email debe rechazarse
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 403

    # Código incorrecto debe rechazarse
    r = client.post("/api/v1/auth/verify-email", json={"email": email, "code": "000000"})
    assert r.status_code == 401

    code = _read_verification_code(db_session, email)
    r = client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["token_type"] == "bearer"

    # El access token debe autorizar /auth/me
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email

    # Ya verificado, login normal debe funcionar
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    login_tokens = r.json()

    # Refresh rota el token: el usado queda inválido, el nuevo funciona
    old_refresh = login_tokens["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200, r.text
    new_tokens = r.json()

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401, "un refresh token ya rotado no debe volver a servir"

    # Logout revoca el refresh token vigente
    r = client.post("/api/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]})
    assert r.status_code == 204
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert r.status_code == 401

    # Recuperación de contraseña
    r = client.post("/api/v1/auth/password-recovery/request", json={"email": email})
    assert r.status_code == 202
    # Email inexistente responde igual (no filtra qué cuentas existen)
    r = client.post("/api/v1/auth/password-recovery/request", json={"email": "nadie@x.com"})
    assert r.status_code == 202

    reset_code = _read_reset_code(db_session, email)
    r = client.post(
        "/api/v1/auth/password-recovery/confirm",
        json={"email": email, "code": reset_code, "new_password": "unanuevaclave1"},
    )
    assert r.status_code == 204, r.text

    r = client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 401, "la contraseña vieja ya no debe funcionar"

    r = client.post("/api/v1/auth/login", json={"email": email, "password": "unanuevaclave1"})
    assert r.status_code == 200, r.text
