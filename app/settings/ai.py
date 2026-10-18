from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from app.settings.base import ENV_FILE, EnvSettings


class AiClientSettings(EnvSettings):
    """Configuro cómo llego al microservicio de IA con las variables AI_*."""

    model_config = SettingsConfigDict(env_prefix="AI_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Con grpc-web, la URL base de su Envoy (https://...); con grpc, el destino host:puerto de la red privada
    SERVICE_URL: str = Field(min_length=1)
    # Sin valor por defecto, como todo secreto: si falta, el backend no arranca
    SERVICE_TOKEN: SecretStr = Field(min_length=32)
    # Hoy la IA está en Render detrás de Envoy, que solo acepta HTTP/1.1 desde internet
    TRANSPORT: Literal["grpc-web", "grpc"] = "grpc-web"
    CONNECT_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    # Lo que espero a que la IA despierte. En Render free medí unos 35 s desde dormida hasta READY
    WAKE_UP_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)
    # Mientras su Envoy responde UNAVAILABLE porque grpcio todavía arranca, reintento cada tanto
    WAKE_UP_RETRY_INTERVAL_SECONDS: float = Field(default=2.0, gt=0)
    # Cada llamada a WarmUp por separado: corta, porque la espera larga la cubre el reintento
    WAKE_UP_CALL_TIMEOUT_SECONDS: float = Field(default=15.0, gt=0)
    # Plazo de una respuesta del asistente en streaming: cubre el arranque en frío más lo que tarda Gemini
    ASSISTANT_TIMEOUT_SECONDS: float = Field(default=90.0, gt=0)
