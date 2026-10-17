from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Cada repo lee su propio .env, en la raíz de KinesiApp-Backend
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class EnvSettings(BaseSettings):
    """Base de la configuración de cada dominio: lee las variables de entorno y el .env."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        # Tolero variables de otros dominios y obsoletas (las SMTP_* de antes de Resend)
        extra="ignore",
    )
