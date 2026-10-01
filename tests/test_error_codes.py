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


def test_unverified_registration_can_be_retried(client, email_outbox):
    # Una cuenta sin verificar no debe bloquear un segundo intento con el mismo email
    # (p. ej. el usuario no recibió el OTP, o dejó pasar el tiempo de espera).
    payload = {"email": "pendiente@kinesiapp.com", "password": "supersecret1", "full_name": "Primero"}
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text

    payload["full_name"] = "Segundo"
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text
    assert r.json()["full_name"] == "Segundo"

    # Sigue siendo una sola cuenta pendiente, no una duplicada
    r = client.post(
        "/api/v1/auth/login", json={"email": "pendiente@kinesiapp.com", "password": "supersecret1"}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "email_not_verified"


def test_login_of_deactivated_verified_account_returns_account_disabled(client, register_and_verify, db_session):
    from app.models.user import User

    register_and_verify("baja@kinesiapp.com")
    user = db_session.query(User).filter(User.email == "baja@kinesiapp.com").one()
    user.is_active = False
    db_session.commit()

    r = client.post("/api/v1/auth/login", json={"email": "baja@kinesiapp.com", "password": "supersecret1"})
    assert r.status_code == 403
    assert r.json()["code"] == "account_disabled"


def test_email_delivery_failure_returns_email_delivery_failed_code(client, monkeypatch):
    from app.core.email import EmailDeliveryError

    def _boom(self, recipient, subject, body):
        raise EmailDeliveryError("SMTP no disponible")

    monkeypatch.setattr("app.core.email.SmtpEmailSender.send", _boom)

    r = client.post(
        "/api/v1/auth/register",
        json={"email": "sinsmtp@kinesiapp.com", "password": "supersecret1", "full_name": "Sin SMTP"},
    )
    assert r.status_code == 503
    assert r.json()["code"] == "email_delivery_failed"


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
