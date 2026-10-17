from functools import lru_cache

from fastapi import Depends

from app.core.config import settings
from app.mail.auth_email_service import AuthEmailService
from app.mail.email_sender import EmailSender
from app.mail.sender_factory import build_email_sender
from app.services.email_domain_checker import EmailDomainChecker


@lru_cache
def get_email_sender() -> EmailSender:
    # Uno por proceso: el SDK de Resend se configura a nivel de módulo
    return build_email_sender(settings)


def get_auth_email_service(sender: EmailSender = Depends(get_email_sender)) -> AuthEmailService:
    return AuthEmailService(sender, settings.OTP_EXPIRE_MINUTES)


def get_email_domain_checker() -> EmailDomainChecker:
    return EmailDomainChecker(settings.EMAIL_DNS_TIMEOUT_SECONDS)
