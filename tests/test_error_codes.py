"""Códigos de error estables (ErrorCode): el cliente traduce por code, no parseando el detail."""
from app.mail.email_sender import EmailDeliveryError


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
        json={"email": "dup@kinesiapp.com", "password": "Supersecret1!", "full_name": "Dup"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "email_already_registered"


def test_unverified_registration_can_be_retried(client, email_outbox):
    # Una cuenta sin verificar no debe bloquear un segundo intento con el mismo email
    # (p. ej. el usuario no recibió el OTP, o dejó pasar el tiempo de espera).
    payload = {"email": "pendiente@kinesiapp.com", "password": "Supersecret1!", "full_name": "Primero"}
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text

    payload["full_name"] = "Segundo"
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text
    assert r.json()["full_name"] == "Segundo"

    # Sigue siendo una sola cuenta pendiente, no una duplicada
    r = client.post(
        "/api/v1/auth/login", json={"email": "pendiente@kinesiapp.com", "password": "Supersecret1!"}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "email_not_verified"


def test_login_of_deactivated_verified_account_returns_account_disabled(client, register_and_verify, db_session):
    from app.models.user import User

    register_and_verify("baja@kinesiapp.com")
    user = db_session.query(User).filter(User.email == "baja@kinesiapp.com").one()
    user.is_active = False
    db_session.commit()

    r = client.post("/api/v1/auth/login", json={"email": "baja@kinesiapp.com", "password": "Supersecret1!"})
    assert r.status_code == 403
    assert r.json()["code"] == "account_disabled"


def test_email_delivery_failure_returns_email_delivery_failed_code(client, fake_email_sender):
    fake_email_sender.error = EmailDeliveryError("Resend no disponible")

    r = client.post(
        "/api/v1/auth/register",
        json={"email": "sinresend@kinesiapp.com", "password": "Supersecret1!", "full_name": "Sin Resend"},
    )
    assert r.status_code == 503
    assert r.json()["code"] == "email_delivery_failed"


def test_missing_resend_api_key_fails_explicitly(client):
    # Sin email_outbox se usa el sender real, que sin RESEND_API_KEY falla sin intentar conectarse
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "sinclave@kinesiapp.com", "password": "Supersecret1!", "full_name": "Sin Clave"},
    )
    assert (r.status_code, r.json()["code"]) == (503, "email_delivery_failed")


def test_login_with_unregistered_email_returns_email_not_registered_code(client):
    r = client.post("/api/v1/auth/login", json={"email": "nadie@kinesiapp.com", "password": "Supersecret1!"})
    assert (r.status_code, r.json()["code"]) == (401, "email_not_registered")


def test_register_rejects_email_domain_that_cannot_receive_email(client, email_outbox, fake_email_domain_checker):
    fake_email_domain_checker.undeliverable_domains.add("dominio-inventado.com")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "ana@dominio-inventado.com", "password": "Supersecret1!", "full_name": "Ana"},
    )
    assert (r.status_code, r.json()["code"]) == (422, "email_domain_undeliverable")
    assert email_outbox == []


def test_not_found_returns_not_found_code(client, register_and_verify):
    token = register_and_verify("nf@kinesiapp.com")
    r = client.get("/api/v1/jump-analyses/99999", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_wrong_otp_returns_invalid_otp_code(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "otpcode@kinesiapp.com", "password": "Supersecret1!", "full_name": "Otp"},
    )
    r = client.post("/api/v1/auth/verify-email", json={"email": "otpcode@kinesiapp.com", "code": "000000"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_otp"
