import logging

import resend
from resend.exceptions import ResendError

from app.mail.email_sender import EmailDeliveryError

logger = logging.getLogger(__name__)


class ResendEmailSender:
    """SDK oficial de Resend. Cualquier falla del proveedor (incluida la red) sale como EmailDeliveryError."""

    def __init__(self, api_key: str, from_email: str, timeout_seconds: int) -> None:
        # El SDK sólo admite configuración global del módulo: hay un único sender por proceso
        # (ver app/services/email_factory.py), así que no hay dos configuraciones que choquen
        resend.api_key = api_key
        resend.default_http_client = resend.RequestsClient(timeout=timeout_seconds)
        self._from_email = from_email

    def send(self, recipient: str, subject: str, body: str) -> None:
        try:
            resend.Emails.send({"from": self._from_email, "to": [recipient], "subject": subject, "text": body})
        except ResendError as error:
            # El SDK convierte también los errores de red en ResendError
            logger.error("Resend rejected the email to %s: %s", recipient, error)
            raise EmailDeliveryError(str(error)) from error
