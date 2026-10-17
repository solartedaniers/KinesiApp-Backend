from collections.abc import Callable

from app.athletes.managed_athletes import owned_athlete
from app.athletes.profile_records import existing_athlete
from app.models.athlete import AthleteProfile
from app.repositories.unit_of_work import UnitOfWork
from app.storage.avatar_files import AvatarFiles, AvatarUpload
from app.storage.image_formats import ImageFormat
from app.storage.upload_tickets import UploadPurpose


class ManagedAthleteAvatars:
    """Manejo la foto de un deportista gestionado con el mismo flujo de dos pasos que el avatar de una cuenta."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], files: AvatarFiles) -> None:
        self._uow_factory = uow_factory
        self._files = files

    async def create_upload(
        self, coach_id: int, athlete_id: int, image_format: ImageFormat, content_length: int
    ) -> AvatarUpload:
        # Compruebo que es suyo antes de firmar nada: si no, cualquier coach podría subir al bucket
        async with self._uow_factory() as uow:
            await owned_athlete(uow, coach_id, athlete_id)
        return self._files.create_upload(athlete_id, UploadPurpose.MANAGED_ATHLETE_AVATAR, image_format, content_length)

    async def confirm_upload(self, coach_id: int, athlete_id: int, upload_id: str) -> AthleteProfile:
        new_url = await self._files.confirmed_url(athlete_id, UploadPurpose.MANAGED_ATHLETE_AVATAR, upload_id)
        return await self._replace(coach_id, athlete_id, new_url)

    async def delete(self, coach_id: int, athlete_id: int) -> AthleteProfile:
        return await self._replace(coach_id, athlete_id, None)

    async def _replace(self, coach_id: int, athlete_id: int, new_url: str | None) -> AthleteProfile:
        async with self._uow_factory() as uow:
            athlete = await owned_athlete(uow, coach_id, athlete_id)
            previous_url = athlete.avatar_url
            # Si confirman dos veces la misma subida, no borro la foto que acaba de quedar
            if previous_url == new_url:
                return athlete
            athlete.avatar_url = new_url
            await uow.commit()
            athlete = await existing_athlete(uow, athlete_id)
        await self._files.discard(previous_url)
        return athlete
