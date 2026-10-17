from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.auth.password_hasher import PasswordHasher
from app.auth.session_issuer import SessionIssuer
from app.auth.session_tokens import SessionTokens, SessionTokenService
from app.core.domain_error import DomainError
from app.repositories.unit_of_work import UnitOfWork


class SessionManagement:
    """Inicio, renuevo y cierro sesiones."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        hasher: PasswordHasher,
        tokens: SessionTokenService,
        sessions: SessionIssuer,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._tokens = tokens
        self._sessions = sessions

    async def login(self, email: str, password: str) -> SessionTokens:
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(email)
            # Revelo que el correo no existe para invitar a registrarse (el registro ya lo revela); con la
            # contraseña incorrecta el error sigue siendo genérico
            if user is None:
                raise DomainError(
                    ErrorReason.ERROR_REASON_EMAIL_NOT_REGISTERED, "No account is registered with this email"
                )
            if not await self._hasher.verify(password, user.hashed_password):
                raise DomainError(ErrorReason.ERROR_REASON_INVALID_CREDENTIALS, "Incorrect email or password")
            # Reviso verificado antes que activo: una cuenta pendiente está inactiva y debe recibir "verifica tu correo"
            if not user.is_verified:
                raise DomainError(ErrorReason.ERROR_REASON_EMAIL_NOT_VERIFIED, "The email must be verified first")
            if not user.is_active:
                raise DomainError(ErrorReason.ERROR_REASON_ACCOUNT_DISABLED, "The account is disabled")
            session = self._sessions.open(uow, user.id)
            await uow.commit()
        return session

    async def refresh(self, refresh_token: str) -> SessionTokens:
        user_id = self._tokens.refresh_token_subject(refresh_token)
        async with self._uow_factory() as uow:
            stored = await uow.refresh_tokens.get_by_token_hash(self._tokens.fingerprint(refresh_token))
            if stored is None or not stored.is_active or stored.user_id != user_id:
                raise _invalid_refresh_token()
            # Roto el token: el usado queda revocado aunque la renovación falle después
            uow.refresh_tokens.revoke(stored)
            user = await uow.users.get(user_id)
            if user is None or not user.is_active:
                await uow.commit()
                raise _invalid_refresh_token()
            session = self._sessions.open(uow, user.id)
            await uow.commit()
        return session

    async def logout(self, refresh_token: str) -> None:
        async with self._uow_factory() as uow:
            stored = await uow.refresh_tokens.get_by_token_hash(self._tokens.fingerprint(refresh_token))
            # Lo hago idempotente: si no existe o ya estaba revocado, el resultado buscado ya se cumple
            if stored is not None and stored.is_active:
                uow.refresh_tokens.revoke(stored)
                await uow.commit()


def _invalid_refresh_token() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_INVALID_REFRESH_TOKEN, "Refresh token is invalid, expired or revoked")
