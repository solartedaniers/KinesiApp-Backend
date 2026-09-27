import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Raised when the SMTP provider does not accept a transactional email."""


class EmailSender:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_email: str,
        use_tls: bool,
        use_ssl: bool,
        timeout_seconds: int,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_email = from_email
        self._use_tls = use_tls
        self._use_ssl = use_ssl
        self._timeout_seconds = timeout_seconds

    def send(self, recipient: str, subject: str, body: str) -> None:
        if self._use_tls and self._use_ssl:
            raise EmailDeliveryError("SMTP TLS and SSL cannot both be enabled")

        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        smtp_class = smtplib.SMTP_SSL if self._use_ssl else smtplib.SMTP
        try:
            with smtp_class(self._host, self._port, timeout=self._timeout_seconds) as server:
                server.ehlo()
                if self._use_tls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                server.login(self._user, self._password)
                refused = server.send_message(message)
                if refused:
                    raise EmailDeliveryError("SMTP rejected one or more recipients")
        except EmailDeliveryError:
            raise
        except (OSError, smtplib.SMTPException) as error:
            logger.exception(
                "SMTP delivery failed for host=%s port=%s recipient=%s error=%s",
                self._host,
                self._port,
                recipient,
                type(error).__name__,
            )
            raise EmailDeliveryError("SMTP delivery failed") from error


def _build_sender() -> EmailSender:
    return EmailSender(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        user=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD.get_secret_value(),
        from_email=settings.SMTP_FROM,
        use_tls=settings.SMTP_USE_TLS,
        use_ssl=settings.SMTP_USE_SSL,
        timeout_seconds=settings.SMTP_TIMEOUT_SECONDS,
    )


def send_verification_email(recipient: str, code: str) -> None:
    _build_sender().send(
        recipient,
        "Verifica tu cuenta de KinesiApp",
        f"Tu código de verificación es: {code}\n"
        f"Vence en {settings.OTP_EXPIRE_MINUTES} minutos.",
    )


def send_password_reset_email(recipient: str, code: str) -> None:
    _build_sender().send(
        recipient,
        "Recuperación de contraseña de KinesiApp",
        f"Tu código de recuperación de contraseña es: {code}\n"
        f"Vence en {settings.OTP_EXPIRE_MINUTES} minutos.\n"
        "Si no pediste este código, podés ignorar este correo.",
    )
