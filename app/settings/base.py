from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Leo el .env de la raíz de KinesiApp-Backend: cada repo tiene el suyo
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class EnvSettings(BaseSettings):
    """Leo las variables de entorno y el .env; la configuración de cada dominio hereda de aquí."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        # Tolero variables de otros dominios y obsoletas (las SMTP_* de antes de Resend)
        extra="ignore",
    )
