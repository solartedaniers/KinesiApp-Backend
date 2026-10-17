from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.auth.auth_mailer import AuthMailer
from app.auth.one_time_codes import CodePurpose, OneTimeCodes
from app.auth.password_replacer import PasswordReplacer
from app.core.domain_error import DomainError
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork


class PasswordRecovery:
    """Recupero la contraseña en tres pasos: pedir el código, validarlo y fijar la nueva."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        codes: OneTimeCodes,
        mailer: AuthMailer,
        passwords: PasswordReplacer,
    ) -> None:
        self._uow_factory = uow_factory
        self._codes = codes
        self._mailer = mailer
        self._passwords = passwords

    async def request_code(self, email: str) -> None:
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(email)
            # Respondo igual exista o no el correo, para no enumerar cuentas
            if user is None:
                return
            code = await self._codes.assign(user, CodePurpose.PASSWORD_RESET)
            await uow.commit()
        await self._mailer.send_password_reset_code(email, code)

    async def verify_code(self, email: str, code: str) -> None:
        # Valido sin consumir el código, pero cuento los intentos fallidos
        async with self._uow_factory() as uow:
            await self._codes.check(uow, await _existing_user(uow, email), CodePurpose.PASSWORD_RESET, code)

    async def confirm(self, email: str, code: str, new_password: str) -> None:
        async with self._uow_factory() as uow:
            user = await _existing_user(uow, email)
            await self._codes.check(uow, user, CodePurpose.PASSWORD_RESET, code)
            await self._passwords.replace(user, new_password)
            self._codes.clear(user, CodePurpose.PASSWORD_RESET)
            # Con la contraseña nueva cierro toda sesión abierta, por si se perdió un dispositivo
            await uow.refresh_tokens.revoke_all_for_user(user.id)
            await uow.commit()


async def _existing_user(uow: UnitOfWork, email: str) -> User:
    user = await uow.users.get_by_email(email)
    if user is None:
        # Devuelvo el mismo error que con un código incorrecto para no revelar qué correos existen
        raise DomainError(ErrorReason.ERROR_REASON_INVALID_OTP, "Invalid or expired verification code")
    return user
