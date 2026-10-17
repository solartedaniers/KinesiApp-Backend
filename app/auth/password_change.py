from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.auth.password_hasher import PasswordHasher
from app.auth.password_replacer import PasswordReplacer
from app.auth.session_issuer import SessionIssuer
from app.auth.session_tokens import SessionTokens
from app.core.domain_error import DomainError
from app.repositories.unit_of_work import UnitOfWork


class PasswordChange:
    """Cambio la contraseña con sesión iniciada: exijo la actual, cierro las demás sesiones y abro una aquí."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        hasher: PasswordHasher,
        passwords: PasswordReplacer,
        sessions: SessionIssuer,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._passwords = passwords
        self._sessions = sessions

    async def change(self, user_id: int, current_password: str, new_password: str) -> SessionTokens:
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None or not await self._hasher.verify(current_password, user.hashed_password):
                raise DomainError(ErrorReason.ERROR_REASON_INVALID_CURRENT_PASSWORD, "Current password is incorrect")
            await self._passwords.replace(user, new_password)
            await uow.refresh_tokens.revoke_all_for_user(user.id)
            session = self._sessions.open(uow, user.id)
            await uow.commit()
        return session
