import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Raised when the SMTP provider does not accept a transactional email."""


class SmtpEmailSender:
    """Transporte SMTP: conexión, autenticación y entrega. No conoce el contenido de los correos."""

    IMPLICIT_SSL_PORT = 465

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_name: str,
        use_tls: bool,
        use_ssl: bool,
        timeout_seconds: int,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_name = from_name
        # El puerto 465 siempre es SSL directo; en ese modo STARTTLS no aplica y se ignora.
        self._use_ssl = use_ssl or port == self.IMPLICIT_SSL_PORT
        self._use_tls = use_tls and not self._use_ssl
        self._timeout_seconds = timeout_seconds

    def _open_connection(self) -> smtplib.SMTP:
        # Contexto explícito: SMTP_SSL sin contexto no valida el certificado del servidor.
        context = ssl.create_default_context()
        if self._use_ssl:
            server = smtplib.SMTP_SSL(
                self._host, self._port, timeout=self._timeout_seconds, context=context
            )
            server.ehlo()
            return server

        server = smtplib.SMTP(self._host, self._port, timeout=self._timeout_seconds)
        server.ehlo()
        if self._use_tls:
            if not server.has_extn("starttls"):
                server.close()
                raise EmailDeliveryError("SMTP server does not support STARTTLS")
            server.starttls(context=context)
            # Tras STARTTLS la sesión se reinicia: hay que volver a saludar antes del login.
            server.ehlo()
        return server

    def _authenticate(self, server: smtplib.SMTP) -> None:
        # Solo AUTH PLAIN: server.login() reintenta con AUTH LOGIN tras un 535 y Gmail cierra
        # el socket, lo que ocultaba el error real de credenciales tras un SMTPServerDisconnected.
        server.user, server.password = self._user, self._password
        try:
            server.auth("PLAIN", server.auth_plain)
        except smtplib.SMTPAuthenticationError as error:
            logger.error(
                "SMTP authentication rejected for user=%s code=%s: check SMTP_USER and the app password",
                self._user,
                error.smtp_code,
            )
            raise

    def send(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        # Gmail con contraseña de aplicación rechaza remitentes distintos a la cuenta
        # autenticada: la dirección siempre es SMTP_USER, solo el nombre visible es libre.
        message["From"] = formataddr((self._from_name, self._user))
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        try:
            with self._open_connection() as server:
                self._authenticate(server)
                # Envelope sender (MAIL FROM) explícito = usuario autenticado
                refused = server.send_message(message, from_addr=self._user, to_addrs=[recipient])
                if refused:
                    raise EmailDeliveryError("SMTP rejected one or more recipients")
        except EmailDeliveryError:
            raise
        except (OSError, smtplib.SMTPException) as error:
            logger.exception(
                "SMTP delivery failed for host=%s port=%s ssl=%s starttls=%s recipient=%s error=%s",
                self._host,
                self._port,
                self._use_ssl,
                self._use_tls,
                recipient,
                type(error).__name__,
            )
            raise EmailDeliveryError("SMTP delivery failed") from error


class AuthEmailService:
    """Redacta los correos de autenticación (verificación y recuperación) y los delega al transporte."""

    def __init__(self, sender: SmtpEmailSender, otp_expire_minutes: int) -> None:
        self._sender = sender
        self._otp_expire_minutes = otp_expire_minutes

    def send_verification_code(self, recipient: str, code: str) -> None:
        self._sender.send(
            recipient,
            "Verifica tu cuenta de KinesiApp",
            f"Tu código de verificación es: {code}\n"
            f"Vence en {self._otp_expire_minutes} minutos.",
        )

    def send_password_reset_code(self, recipient: str, code: str) -> None:
        self._sender.send(
            recipient,
            "Recuperación de contraseña de KinesiApp",
            f"Tu código de recuperación de contraseña es: {code}\n"
            f"Vence en {self._otp_expire_minutes} minutos.\n"
            "Si no pediste este código, podés ignorar este correo.",
        )


def get_auth_email_service() -> AuthEmailService:
    sender = SmtpEmailSender(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        user=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD.get_secret_value(),
        from_name=settings.SMTP_FROM_NAME,
        use_tls=settings.SMTP_USE_TLS,
        use_ssl=settings.SMTP_USE_SSL,
        timeout_seconds=settings.SMTP_TIMEOUT_SECONDS,
    )
    return AuthEmailService(sender, settings.OTP_EXPIRE_MINUTES)
