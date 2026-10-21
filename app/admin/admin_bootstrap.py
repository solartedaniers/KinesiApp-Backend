from collections.abc import Callable

from app.admin.inputs import AccountInput
from app.auth.password_hasher import PasswordHasher
from app.models.user import User, UserRole
from app.repositories.unit_of_work import UnitOfWork


class AdminBootstrap:
    """Creo el primer admin o promuevo a uno existente. Lo corre quien opera el servidor, así que no envío código."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], hasher: PasswordHasher) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher

    async def run(self, data: AccountInput) -> User:
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(data.email)
            if user is None:
                user = User(
                    email=data.email,
                    hashed_password=await self._hasher.hash(data.password),
                    full_name=data.full_name,
                )
            # Idempotente: si ya existía, solo lo promuevo; su contraseña no la toco
            user.role = UserRole.ADMIN
            user.is_active = True
            user.is_verified = True
            uow.users.add(user)
            await uow.commit()
            await uow.users.refresh(user)
        return user
