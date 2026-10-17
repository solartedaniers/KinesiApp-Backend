from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.admin.user_directory import other_user
from app.core.domain_error import DomainError
from app.models.user import User, UserRole
from app.repositories.unit_of_work import UnitOfWork


class UserRoleAssignment:
    """Único camino para volverse COACH o ADMIN: un admin autenticado cambia el rol de otra cuenta."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def assign(self, admin_id: int, user_id: int, role: UserRole) -> User:
        async with self._uow_factory() as uow:
            user = await other_user(uow, admin_id, user_id)
            # Un coach que deja de serlo dejaría huérfanos a sus deportistas gestionados
            leaves_coaching = user.role == UserRole.COACH and role != UserRole.COACH
            if leaves_coaching and await uow.athletes.count_by_coach(user.id):
                raise DomainError(
                    ErrorReason.ERROR_REASON_COACH_HAS_ATHLETES,
                    "Reassign the coach's athletes before changing the role",
                )
            user.role = role
            await uow.commit()
        return user
