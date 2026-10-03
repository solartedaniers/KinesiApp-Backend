import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """El proveedor no aceptó el correo, no respondió o no está configurado."""


class EmailSender(Protocol):
    """Frontera hacia el proveedor de correo: el resto de la app no sabe que es Resend."""

    def send(self, recipient: str, subject: str, body: str) -> None: ...


class UnconfiguredEmailSender:
    """Se usa cuando no hay API key: cada envío falla con un error explícito, sin intentar conectarse."""

    def send(self, recipient: str, subject: str, body: str) -> None:
        logger.error("Email to %s not sent: RESEND_API_KEY is not configured", recipient)
        raise EmailDeliveryError("RESEND_API_KEY is not configured")
