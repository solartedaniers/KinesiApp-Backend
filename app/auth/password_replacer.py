from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.auth.password_hasher import PasswordHasher
from app.core.domain_error import DomainError
from app.models.user import User


class PasswordReplacer:
    """Cambia el hash de la contraseña, rechazando la misma que ya tiene (recuperación y cambio)."""

    def __init__(self, hasher: PasswordHasher) -> None:
        self._hasher = hasher

    async def replace(self, user: User, new_password: str) -> None:
        # Comparo contra el hash guardado: la contraseña actual nunca existe en texto plano
        if await self._hasher.verify(new_password, user.hashed_password):
            raise DomainError(
                ErrorReason.ERROR_REASON_PASSWORD_REUSED, "New password must be different from the current one"
            )
        user.hashed_password = await self._hasher.hash(new_password)
