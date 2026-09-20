import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    """Envío de correos transaccionales vía SMTP (sin dependencias externas)."""

    def __init__(
        self, host: str, port: int, user: str, password: str, from_email: str, use_tls: bool
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_email = from_email
        self._use_tls = use_tls

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        # ponytail: un correo fallido no debe tumbar el registro/recuperación; solo se loguea.
        # Si el volumen crece, mover a una cola con reintentos (Celery/RQ).
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as server:
                if self._use_tls:
                    server.starttls()
                if self._user:
                    server.login(self._user, self._password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException):
            logger.warning("No se pudo enviar el correo a %s", to, exc_info=True)


def _build_sender() -> EmailSender:
    return EmailSender(
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        settings.SMTP_USER,
        settings.SMTP_PASSWORD,
        settings.SMTP_FROM_EMAIL,
        settings.SMTP_USE_TLS,
    )


def send_verification_email(to: str, code: str) -> None:
    _build_sender().send(
        to,
        "Verifica tu cuenta de KinesiApp",
        f"Tu código de verificación es: {code}\n"
        f"Expira en {settings.OTP_EXPIRE_MINUTES} minutos.",
    )


def send_password_reset_email(to: str, code: str) -> None:
    _build_sender().send(
        to,
        "Recuperación de contraseña - KinesiApp",
        f"Tu código de recuperación es: {code}\n"
        f"Expira en {settings.OTP_EXPIRE_MINUTES} minutos.\n"
        "Si no solicitaste esto, ignora este correo.",
    )
