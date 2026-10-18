import pytest
from pydantic import ValidationError

from app.settings.ai import AiClientSettings
from app.settings.analysis import AnalysisSettings, ensure_lease_outlasts_ai_call
from app.settings.auth import AuthSettings


def test_auth_settings_refuse_to_start_without_a_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        AuthSettings(_env_file=None)


def test_a_missing_variable_never_shows_the_secrets_in_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "jwt-secret-that-must-never-reach-the-logs"
    monkeypatch.setenv("JWT_SECRET_KEY", secret)
    monkeypatch.delenv("OTP_EXPIRE_MINUTES", raising=False)

    with pytest.raises(ValidationError, match="OTP_EXPIRE_MINUTES") as raised:
        AuthSettings(_env_file=None)

    # pydantic recorta el valor por el medio: sin ocultarlo, mostraba el principio y el final del secreto
    message = str(raised.value)
    assert secret[:5] not in message and secret[-10:] not in message


def test_an_empty_secret_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    monkeypatch.setenv("OTP_EXPIRE_MINUTES", "10")

    with pytest.raises(ValidationError, match=r"JWT_SECRET_KEY\s+Field required"):
        AuthSettings(_env_file=None)


def test_the_processing_lease_must_outlast_waking_the_ai_plus_the_analysis_call() -> None:
    ai = AiClientSettings(_env_file=None, SERVICE_URL="ai.test:443", SERVICE_TOKEN="t" * 32, WAKE_UP_TIMEOUT_SECONDS=60)
    analysis = AnalysisSettings(_env_file=None, STREAM_TIMEOUT_SECONDS=180, PROCESSING_LEASE_SECONDS=240)

    with pytest.raises(ValueError, match="ANALYSIS_PROCESSING_LEASE_SECONDS"):
        ensure_lease_outlasts_ai_call(analysis, ai)
    ensure_lease_outlasts_ai_call(AnalysisSettings(_env_file=None), ai)
