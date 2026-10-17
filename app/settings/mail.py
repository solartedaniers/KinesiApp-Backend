from pydantic import Field, SecretStr

from app.settings.base import EnvSettings


class MailSettings(EnvSettings):
    """Configuro el correo transaccional con Resend y la verificación DNS/MX del dominio en el registro."""

    EMAIL_DNS_TIMEOUT_SECONDS: int = Field(default=5, gt=0)
    # Sin RESEND_API_KEY hago fallar el envío con un error explícito (email_delivery_failed).
    # onboarding@resend.dev solo entrega al dueño de la cuenta de Resend: para usuarios reales hay que
    # verificar un dominio. Admite "Nombre <correo>"
    RESEND_API_KEY: SecretStr | None = None
    RESEND_FROM_EMAIL: str = Field(default="onboarding@resend.dev", min_length=1)
    RESEND_TIMEOUT_SECONDS: int = Field(default=15, gt=0, le=120)
