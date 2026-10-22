from collections.abc import Callable

from app.account.account_profile import own_account
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork
from app.storage.avatar_files import AvatarFiles, AvatarUpload
from app.storage.image_formats import ImageFormat
from app.storage.upload_tickets import UploadPurpose


class AvatarManagement:
    """Manejo el avatar de la propia cuenta: el navegador lo sube directo al bucket y yo solo firmo y verifico."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], files: AvatarFiles) -> None:
        self._uow_factory = uow_factory
        self._files = files

    def create_upload(self, user_id: int, image_format: ImageFormat, content_length: int) -> AvatarUpload:
        return self._files.create_upload(user_id, UploadPurpose.AVATAR, image_format, content_length)

    async def confirm_upload(self, user_id: int, upload_id: str) -> User:
        new_url = await self._files.confirmed_url(user_id, UploadPurpose.AVATAR, upload_id)
        async with self._uow_factory() as uow:
            user = await own_account(uow, user_id)
            previous_url = user.avatar_url
            # Si confirman dos veces la misma subida, no borro la foto que acaba de quedar
            if previous_url == new_url:
                return user
            user.avatar_url = new_url
            await uow.commit()
        await self._files.discard(previous_url)
        return user

    async def delete(self, user_id: int) -> User:
        async with self._uow_factory() as uow:
            user = await own_account(uow, user_id)
            previous_url = user.avatar_url
            user.avatar_url = None
            await uow.commit()
        await self._files.discard(previous_url)
        return user
