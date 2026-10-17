import pytest
from pydantic import ValidationError

from app.settings.auth import AuthSettings


def test_auth_settings_refuse_to_start_without_a_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        AuthSettings(_env_file=None)
