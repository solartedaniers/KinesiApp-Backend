from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings, settings
from app.mail.auth_email_service import AuthEmailService
from app.mail.email_sender import EmailSender, UnconfiguredEmailSender
from app.mail.resend_email_sender import ResendEmailSender


def build_email_sender(config: Settings) -> EmailSender:
    if config.RESEND_API_KEY is None or not config.RESEND_API_KEY.get_secret_value():
        return UnconfiguredEmailSender()
    return ResendEmailSender(
        api_key=config.RESEND_API_KEY.get_secret_value(),
        from_email=config.RESEND_FROM_EMAIL,
        timeout_seconds=config.RESEND_TIMEOUT_SECONDS,
    )


@lru_cache
def get_email_sender() -> EmailSender:
    # Uno por proceso: el SDK de Resend se configura a nivel de módulo
    return build_email_sender(settings)


def get_auth_email_service(sender: EmailSender = Depends(get_email_sender)) -> AuthEmailService:
    return AuthEmailService(sender, settings.OTP_EXPIRE_MINUTES)
