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
        # Oculto los valores en los errores de validación: si no, al faltar una variable el log mostraría
        # el principio y el final de los secretos del .env
        hide_input_in_errors=True,
        # Tomo una variable vacía como no definida, así "JWT_SECRET_KEY=" cuenta como faltante
        env_ignore_empty=True,
    )
