from pydantic import Field, SecretStr

from app.settings.base import EnvSettings


class ChatSettings(EnvSettings):
    """Configuro el chat con Gemini; sin GEMINI_API_KEY respondo assistant_unavailable."""

    GEMINI_API_KEY: SecretStr | None = None
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    GEMINI_MAX_OUTPUT_TOKENS: int = Field(default=1024, gt=0)
    CHAT_MESSAGE_MAX_CHARS: int = Field(default=1000, gt=0)
    CHAT_HISTORY_MAX_MESSAGES: int = Field(default=10, ge=0)
    CHAT_PROMPT_MAX_REPETITIONS: int = Field(default=5, ge=0)
    CHAT_RATE_LIMIT_PER_USER_PER_HOUR: int = Field(default=20, gt=0)
    # Lo dejo por debajo del límite de requests por minuto del free tier del modelo
    CHAT_RATE_LIMIT_GLOBAL_PER_MINUTE: int = Field(default=8, gt=0)
