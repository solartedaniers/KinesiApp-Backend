from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación, cargada desde variables de entorno (.env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    PROJECT_NAME: str = "KinesiApp API"
    API_V1_PREFIX: str = "/api/v1"

    POSTGRES_USER: str = "kinesiapp"
    POSTGRES_PASSWORD: str = "kinesiapp"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
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
    def database_url(self) -> str:
        # Se compone en runtime para no quemar credenciales en el código
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    # Cacheada para no releer/parsear el .env en cada inyección de dependencia
    return Settings()


settings = get_settings()
