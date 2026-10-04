"""Recuperación en 3 pasos, cambio de contraseña, política de contraseñas, perfil y avatares."""
import base64
import re

from app.models.user import User
from app.storage.object_storage import ObjectStorageError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_AVATAR = {"content_type": "image/png", "data_base64": base64.b64encode(PNG_BYTES).decode()}
PROFILE = {"gender": "male", "height_cm": 175, "weight_kg": 70, "birth_date": "2000-01-01"}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request_reset_code(client, email_outbox, email: str) -> str:
    assert client.post("/api/v1/auth/password-recovery/request", json={"email": email}).status_code == 202
    message = next(item for item in reversed(email_outbox) if item["to"] == email)
    return re.search(r"\b\d{6}\b", message["body"]).group()


def test_register_requires_every_password_character_class(client, email_outbox):
    for weak, missing in [
        ("onlyletters", "one uppercase letter, one digit, one special character"),
        ("NOLOWER1!", "one lowercase letter"),
        ("NoDigits!", "one digit"),
        ("NoSpecial1", "one special character"),
        ("Sh0rt!", None),  # demasiado corta
    ]:
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "weak@kinesiapp.com", "password": weak, "full_name": "Weak"},
        )
        assert r.status_code == 422, weak
        if missing:
            assert f"at least {missing}" in r.text
    # Tildes y ñ cuentan como letras y el guion bajo como especial; el espacio se permite pero no cuenta
    for strong in ("Ñandú2024!", "Clave segura 1!", "Clave_segura1"):
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "strong@kinesiapp.com", "password": strong, "full_name": "Strong"},
        )
        assert r.status_code == 201, (strong, r.text)


def test_full_name_accepts_only_letters_and_spaces(client, email_outbox):
    for invalid in ("Ana3", "Ana_Pérez", "R2-D2", "Ana!", "   ", "Luis ²"):
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "name@kinesiapp.com", "password": "Supersecret1!", "full_name": invalid},
        )
        assert r.status_code == 422, invalid
    # Tildes, ñ y diéresis (también en forma descompuesta, como la mandan algunos teclados);
    # los espacios sobrantes se colapsan
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "name@kinesiapp.com", "password": "Supersecret1!", "full_name": "  Mari\u0301a   Ñúñez  Güell "},
    )
    assert r.status_code == 201, r.text
    assert r.json()["full_name"] == "María Ñúñez Güell"


def test_recovery_verify_step_does_not_consume_code(client, register_and_verify, email_outbox):
    register_and_verify("steps@kinesiapp.com")
    code = _request_reset_code(client, email_outbox, "steps@kinesiapp.com")

    wrong = "000000" if code != "000000" else "111111"
    r = client.post("/api/v1/auth/password-recovery/verify", json={"email": "steps@kinesiapp.com", "code": wrong})
    assert r.json()["code"] == "invalid_otp"
    r = client.post("/api/v1/auth/password-recovery/verify", json={"email": "steps@kinesiapp.com", "code": code})
    assert r.status_code == 204

    r = client.post(
        "/api/v1/auth/password-recovery/confirm",
        json={"email": "steps@kinesiapp.com", "code": code, "new_password": "BrandNew123!"},
    )
    assert r.status_code == 204


def test_recovery_verify_unknown_email_looks_like_wrong_code(client):
    r = client.post("/api/v1/auth/password-recovery/verify", json={"email": "ghost@kinesiapp.com", "code": "123456"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_otp"


def test_recovery_rejects_current_password(client, register_and_verify, email_outbox):
    register_and_verify("reuse@kinesiapp.com")
    code = _request_reset_code(client, email_outbox, "reuse@kinesiapp.com")
    r = client.post(
        "/api/v1/auth/password-recovery/confirm",
        json={"email": "reuse@kinesiapp.com", "code": code, "new_password": "Supersecret1!"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "password_reused"


def test_change_password_flow(client, register_and_verify, db_session):
    token = register_and_verify("change@kinesiapp.com")

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "wrongpass1", "new_password": "Another123!"},
        headers=_auth(token),
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_current_password"

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "Supersecret1!", "new_password": "Supersecret1!"},
        headers=_auth(token),
    )
    assert r.json()["code"] == "password_reused"

    r = client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "Supersecret1!", "new_password": "Another123!"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["refresh_token"]

    stored = db_session.query(User).filter(User.email == "change@kinesiapp.com").one()
    assert stored.hashed_password.startswith("$2") and "Another123!" not in stored.hashed_password
    assert client.post("/api/v1/auth/login", json={"email": "change@kinesiapp.com", "password": "Another123!"}).status_code == 200


def test_update_profile_and_avatar(client, register_and_verify, fake_image_storage):
    token = register_and_verify("me@kinesiapp.com")

    assert client.patch("/api/v1/users/me", json={"full_name": "Nombre 2"}, headers=_auth(token)).status_code == 422
    r = client.patch("/api/v1/users/me", json={"full_name": "Nuevo Nombre"}, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["full_name"] == "Nuevo Nombre"

    r = client.put("/api/v1/users/me/avatar", json=PNG_AVATAR, headers=_auth(token))
    assert r.status_code == 200
    # Se guarda la URL pública del objeto en el bucket de imágenes, no la imagen
    first_url = r.json()["avatar_url"]
    assert first_url.startswith(fake_image_storage.public_base_url) and first_url.endswith(".png")
    assert fake_image_storage.objects[first_url] == (base64.b64decode(PNG_AVATAR["data_base64"]), "image/png")

    # Cambiarla reemplaza el objeto: la anterior se borra del bucket
    second_url = client.put("/api/v1/users/me/avatar", json=PNG_AVATAR, headers=_auth(token)).json()["avatar_url"]
    assert second_url != first_url and set(fake_image_storage.objects) == {second_url}

    r = client.delete("/api/v1/users/me/avatar", headers=_auth(token))
    assert r.json()["avatar_url"] is None
    assert fake_image_storage.objects == {}


def test_avatar_storage_failure_is_503_and_keeps_the_current_photo(client, register_and_verify, fake_image_storage):
    token = register_and_verify("storage-down@kinesiapp.com")
    url = client.put("/api/v1/users/me/avatar", json=PNG_AVATAR, headers=_auth(token)).json()["avatar_url"]
    fake_image_storage.error = ObjectStorageError("down")

    r = client.put("/api/v1/users/me/avatar", json=PNG_AVATAR, headers=_auth(token))
    assert (r.status_code, r.json()["code"]) == (503, "storage_unavailable")
    assert client.get("/api/v1/auth/me", headers=_auth(token)).json()["avatar_url"] == url


def test_avatar_rejects_mismatched_content(client, register_and_verify):
    token = register_and_verify("fake@kinesiapp.com")
    r = client.put(
        "/api/v1/users/me/avatar",
        json={"content_type": "image/jpeg", "data_base64": PNG_AVATAR["data_base64"]},
        headers=_auth(token),
    )
    assert r.status_code == 422
    r = client.put(
        "/api/v1/users/me/avatar",
        json={"content_type": "image/png", "data_base64": "not base64!"},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_coach_sets_managed_athlete_avatar_and_team_analyses(
    client, register_and_verify, grant_consent, upload_jump, fake_image_storage
):
    coach = register_and_verify("avatar-coach@kinesiapp.com", role="coach")
    other = register_and_verify("other-coach@kinesiapp.com", role="coach")
    athlete = client.post(
        "/api/v1/coach/athletes", json={**PROFILE, "full_name": "Ana"}, headers=_auth(coach)
    ).json()

    r = client.put(f"/api/v1/coach/athletes/{athlete['id']}/avatar", json=PNG_AVATAR, headers=_auth(coach))
    assert r.status_code == 200
    assert r.json()["display_avatar"] in fake_image_storage.objects
    assert client.put(
        f"/api/v1/coach/athletes/{athlete['id']}/avatar", json=PNG_AVATAR, headers=_auth(other)
    ).status_code == 404

    grant_consent(coach)
    assert upload_jump(coach, athlete["id"]).status_code == 202
    team = client.get("/api/v1/jump-analyses/team", headers=_auth(coach)).json()
    assert [item["athlete_id"] for item in team] == [athlete["id"]]
    assert client.get("/api/v1/jump-analyses/team", headers=_auth(other)).json() == []

    # Borrar al deportista gestionado borra también su foto del bucket
    assert client.delete(f"/api/v1/coach/athletes/{athlete['id']}", headers=_auth(coach)).status_code == 204
    assert fake_image_storage.objects == {}
