import asyncio
from typing import Protocol

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError
from app.mail.auth_email_service import AuthEmailService
from app.mail.email_sender import EmailDeliveryError


class AuthMailer(Protocol):
    async def send_verification_code(self, recipient: str, code: str) -> None: ...

    async def send_password_reset_code(self, recipient: str, code: str) -> None: ...


class ThreadedAuthMailer:
    """Adapter: el SDK de Resend es bloqueante, así que lo llamo en un hilo y traduzco su error al del contrato."""

    def __init__(self, emails: AuthEmailService) -> None:
        self._emails = emails

    async def send_verification_code(self, recipient: str, code: str) -> None:
        await self._send(self._emails.send_verification_code, recipient, code)

    async def send_password_reset_code(self, recipient: str, code: str) -> None:
        await self._send(self._emails.send_password_reset_code, recipient, code)

    @staticmethod
    async def _send(send, recipient: str, code: str) -> None:
        try:
            await asyncio.to_thread(send, recipient, code)
        except EmailDeliveryError as error:
            raise DomainError(ErrorReason.ERROR_REASON_EMAIL_DELIVERY_FAILED, "The email could not be delivered") from error
