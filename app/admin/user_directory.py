from collections.abc import Callable
from dataclasses import dataclass

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class UserPage:
    users: list[User]
    # Lo dejo en None cuando no quedan más cuentas después de esta página
    last_id: int | None


class UserDirectory:
    """Le muestro al admin las cuentas: una por id o todas por páginas."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def get(self, user_id: int) -> User:
        async with self._uow_factory() as uow:
            return await existing_user(uow, user_id)

    async def list(self, after_id: int, limit: int) -> UserPage:
        async with self._uow_factory() as uow:
            # Pido una de más para saber si hay otra página sin contar toda la tabla
            users = await uow.users.list_after(after_id, limit + 1)
        has_more = len(users) > limit
        users = users[:limit]
        return UserPage(users, users[-1].id if has_more else None)


async def existing_user(uow: UnitOfWork, user_id: int) -> User:
    user = await uow.users.get(user_id)
    if user is None:
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The user does not exist")
    return user


async def other_user(uow: UnitOfWork, admin_id: int, user_id: int) -> User:
    # No dejo que un admin se cambie el rol ni se desactive a sí mismo: así nunca faltan administradores
    if user_id == admin_id:
        raise DomainError(ErrorReason.ERROR_REASON_CANNOT_MODIFY_OWN_ACCOUNT, "You cannot modify your own account")
    return await existing_user(uow, user_id)
