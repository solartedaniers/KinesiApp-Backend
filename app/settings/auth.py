from pydantic import Field, SecretStr

from app.settings.base import EnvSettings


class AuthSettings(EnvSettings):
    """Configuro los tokens de sesión y los códigos de un solo uso."""

    # No le doy valor por defecto: con una clave conocida cualquiera podría firmar tokens válidos
    JWT_SECRET_KEY: SecretStr = Field(min_length=1)
    JWT_ALGORITHM: str = Field(default="HS256", min_length=1)
    # Le doy al access una vida corta para el uso normal y al refresh una larga solo para renovarlo
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, gt=0)
    OTP_EXPIRE_MINUTES: int = Field(gt=0)
    OTP_LENGTH: int = Field(default=6, ge=4, le=10)
    OTP_MAX_ATTEMPTS: int = Field(default=5, gt=0)


class PasswordPolicySettings(EnvSettings):
    """Defino la política de contraseñas nuevas; el frontend la recibe por SystemService.GetClientPolicy."""

    PASSWORD_MIN_LENGTH: int = Field(default=8, ge=8)
    PASSWORD_MAX_LENGTH: int = Field(default=128, gt=0)
