from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Configuración de la aplicación, cargada desde variables de entorno (.env)."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
    )

    PROJECT_NAME: str = "KinesiApp API"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    CORS_ALLOW_ORIGIN_REGEX: str | None = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    POSTGRES_USER: str = "kinesiapp"
    POSTGRES_PASSWORD: str = "kinesiapp"
    POSTGRES_HOST: str = "localhost"
    # En desarrollo local de Windows, docker-compose publica PostgreSQL aquí.
    # El servicio API de Docker sobrescribe el puerto a 5432.
    POSTGRES_PORT: int = 5434
    POSTGRES_DB: str = "kinesiapp"

    # JWT: access de vida corta para uso normal, refresh de vida larga solo para renovarlo
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    OTP_EXPIRE_MINUTES: int = 10

    # SMTP para correos transaccionales (verificación de cuenta, recuperación de contraseña)
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@kinesiapp.com"
    SMTP_USE_TLS: bool = True

    @property
    def database_url(self) -> URL:
        # URL.create escapa correctamente credenciales con @, :, / o %.
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )


@lru_cache
def get_settings() -> Settings:
    # Cacheada para no releer/parsear el .env en cada inyección de dependencia
    return Settings()


settings = get_settings()
