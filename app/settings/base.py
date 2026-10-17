from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env sigue en la raíz del espacio de trabajo, donde lo dejó el antiguo monorepo
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class EnvSettings(BaseSettings):
    """Base de la configuración de cada dominio: lee las variables de entorno y el .env."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        # Tolero variables de otros dominios y obsoletas (las SMTP_* de antes de Resend)
        extra="ignore",
    )
