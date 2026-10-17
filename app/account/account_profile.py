from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork


class AccountProfile:
    """Lee la cuenta de quien llama y edita su nombre."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def get(self, user_id: int) -> User:
        async with self._uow_factory() as uow:
            return await own_account(uow, user_id)

    async def rename(self, user_id: int, full_name: str) -> User:
        async with self._uow_factory() as uow:
            user = await own_account(uow, user_id)
            user.full_name = full_name
            await uow.commit()
        return user


async def own_account(uow: UnitOfWork, user_id: int) -> User:
    # El interceptor ya validó la cuenta; solo falta si la borraron entre tanto
    user = await uow.users.get(user_id)
    if user is None:
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The account does not exist")
    return user
