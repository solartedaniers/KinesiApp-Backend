"""Códigos de error estables (ErrorCode): el cliente traduce por code, no parseando el detail."""


def test_login_with_wrong_password_returns_invalid_credentials_code(client, register_and_verify):
    register_and_verify("coderr@kinesiapp.com")
    r = client.post(
        "/api/v1/auth/login", json={"email": "coderr@kinesiapp.com", "password": "wrongpassword"}
    )
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_duplicate_registration_returns_email_already_registered_code(client, register_and_verify):
    register_and_verify("dup@kinesiapp.com")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@kinesiapp.com", "password": "supersecret1", "full_name": "Dup"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "email_already_registered"


def test_not_found_returns_not_found_code(client, register_and_verify):
    token = register_and_verify("nf@kinesiapp.com")
    r = client.get("/api/v1/jump-analyses/99999", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_wrong_otp_returns_invalid_otp_code(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "otpcode@kinesiapp.com", "password": "supersecret1", "full_name": "Otp"},
    )
    r = client.post("/api/v1/auth/verify-email", json={"email": "otpcode@kinesiapp.com", "code": "000000"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_otp"
