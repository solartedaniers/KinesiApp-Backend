from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.auth.auth_mailer import AuthMailer
from app.auth.one_time_codes import CodePurpose, OneTimeCodes
from app.auth.session_issuer import SessionIssuer
from app.auth.session_tokens import SessionTokens
from app.core.domain_error import DomainError
from app.repositories.unit_of_work import UnitOfWork


class EmailVerification:
    """Reenvío el código de verificación y, con el código correcto, activo la cuenta y abro la primera sesión."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        codes: OneTimeCodes,
        mailer: AuthMailer,
        sessions: SessionIssuer,
    ) -> None:
        self._uow_factory = uow_factory
        self._codes = codes
        self._mailer = mailer
        self._sessions = sessions

    async def request_code(self, email: str) -> None:
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(email)
            # No doy error si no existe o ya está verificada: así la respuesta no revela qué cuentas hay
            if user is None or user.is_verified:
                return
            code = await self._codes.assign(user, CodePurpose.VERIFICATION)
            await uow.commit()
        await self._mailer.send_verification_code(email, code)

    async def verify(self, email: str, code: str) -> SessionTokens:
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(email)
            if user is None:
                raise DomainError(ErrorReason.ERROR_REASON_INVALID_OTP, "Invalid or expired verification code")
            await self._codes.check(uow, user, CodePurpose.VERIFICATION, code)
            user.is_verified = True
            user.is_active = True
            self._codes.clear(user, CodePurpose.VERIFICATION)
            session = self._sessions.open(uow, user.id)
            await uow.commit()
        return session
