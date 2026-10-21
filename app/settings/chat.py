from pydantic import Field

from app.settings.base import EnvSettings


class ChatSettings(EnvSettings):
    """Limito los mensajes del chat. El modelo y el prompt los configura la IA, no el backend."""

    CHAT_MESSAGE_MAX_CHARS: int = Field(default=1000, gt=0)
    CHAT_RATE_LIMIT_PER_USER_PER_HOUR: int = Field(default=20, gt=0)
    # Lo dejo por debajo del límite de requests por minuto del free tier del modelo
    CHAT_RATE_LIMIT_GLOBAL_PER_MINUTE: int = Field(default=8, gt=0)
