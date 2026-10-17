from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.admin.inputs import NewUserInput
from app.auth.password_hasher import PasswordHasher
from app.core.domain_error import DomainError
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork


class UserProvisioning:
    """Alta de cuentas por un admin: quedan sin verificar y su dueño las activa con el código al iniciar sesión."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], hasher: PasswordHasher) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher

    async def create(self, data: NewUserInput) -> User:
        async with self._uow_factory() as uow:
            # A diferencia del registro, no reemplazo una cuenta sin verificar: quizá su dueño espera el código
            if await uow.users.get_by_email(data.email) is not None:
                raise DomainError(ErrorReason.ERROR_REASON_EMAIL_ALREADY_REGISTERED, "The email is already registered")
            user = User(
                email=data.email,
                hashed_password=await self._hasher.hash(data.password),
                full_name=data.full_name,
                role=data.role,
                # Igual que en el registro: la verificación del correo es la que activa la cuenta
                is_active=False,
                is_verified=False,
            )
            uow.users.add(user)
            await uow.commit()
            await uow.users.refresh(user)
        return user
