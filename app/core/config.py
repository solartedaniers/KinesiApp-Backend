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
