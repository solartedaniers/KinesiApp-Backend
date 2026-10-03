from app.mail.email_sender import EmailSender


class AuthEmailService:
    """Redacta los correos de autenticación (verificación y recuperación) y los delega al transporte."""

    def __init__(self, sender: EmailSender, otp_expire_minutes: int) -> None:
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
