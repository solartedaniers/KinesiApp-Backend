from pydantic import Field

from app.settings.base import EnvSettings


class HttpApiSettings(EnvSettings):
    """Configuro la API REST de FastAPI, que desaparece cuando el frontend termine de migrar a gRPC."""

    PROJECT_NAME: str = "KinesiApp API"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    CORS_ALLOW_ORIGIN_REGEX: str | None = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
