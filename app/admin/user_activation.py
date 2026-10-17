from collections.abc import Callable

from app.admin.user_directory import other_user
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork


class UserActivation:
    """Activa o desactiva otra cuenta sin borrar sus datos."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def set_active(self, admin_id: int, user_id: int, is_active: bool) -> User:
        async with self._uow_factory() as uow:
            user = await other_user(uow, admin_id, user_id)
            user.is_active = is_active
            # Al desactivar corto también las sesiones abiertas; el access token vigente lo frena el interceptor
            if not is_active:
                await uow.refresh_tokens.revoke_all_for_user(user.id)
            await uow.commit()
        return user
