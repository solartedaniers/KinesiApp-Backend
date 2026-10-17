import logging
from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.athletes.inputs import ManagedAthleteInput, ManagedAthleteUpdateInput
from app.athletes.profile_records import existing_athlete
from app.core.domain_error import DomainError
from app.models.athlete import AthleteProfile
from app.repositories.unit_of_work import UnitOfWork
from app.storage.avatar_files import AvatarFiles
from app.storage.signed_storage import SignedObjectStorage

logger = logging.getLogger(__name__)


class ManagedAthletes:
    """Le dejo a un coach crear, editar y borrar a sus deportistas sin cuenta; nunca los de otro coach."""

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], avatar_files: AvatarFiles, videos: SignedObjectStorage
    ) -> None:
        self._uow_factory = uow_factory
        self._avatar_files = avatar_files
        self._videos = videos

    async def list(self, coach_id: int) -> list[AthleteProfile]:
        async with self._uow_factory() as uow:
            return await uow.athletes.list_managed_by_coach(coach_id)

    async def create(self, coach_id: int, data: ManagedAthleteInput) -> AthleteProfile:
        async with self._uow_factory() as uow:
            athlete = AthleteProfile(coach_id=coach_id, full_name=data.full_name, **data.biometrics.model_dump())
            uow.athletes.add(athlete)
            await uow.commit()
            return await existing_athlete(uow, athlete.id)

    async def update(self, coach_id: int, data: ManagedAthleteUpdateInput) -> AthleteProfile:
        async with self._uow_factory() as uow:
            athlete = await owned_athlete(uow, coach_id, data.athlete_id)
            for field, value in data.changes().items():
                setattr(athlete, field, value)
            await uow.commit()
            return await existing_athlete(uow, athlete.id)

    async def delete(self, coach_id: int, athlete_id: int) -> None:
        async with self._uow_factory() as uow:
            athlete = await owned_athlete(uow, coach_id, athlete_id)
            avatar_url = athlete.avatar_url
            video_urls = [analysis.video_reference for analysis in athlete.jump_analyses]
            await uow.athletes.delete(athlete)
            await uow.commit()
        # Borro los archivos después de confirmar la base: si falla, quedan huérfanos pero nada apunta a ellos
        await self._avatar_files.discard(avatar_url)
        for video_url in video_urls:
            await self._discard_video(video_url)

    async def _discard_video(self, video_url: str) -> None:
        try:
            await self._videos.delete(self._videos.key_from_url(video_url))
        except (DomainError, ValueError) as error:
            # Los videos del REST viven en el bucket público de producción: esos no los toco desde aquí
            logger.warning("Could not delete video %s: %s", video_url, error)


async def owned_athlete(uow: UnitOfWork, coach_id: int, athlete_id: int) -> AthleteProfile:
    athlete = await uow.athletes.get_managed_by_coach(athlete_id, coach_id)
    if athlete is None:
        # Respondo NOT_FOUND y no PERMISSION_DENIED para no revelar qué ids tienen otros coaches
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The managed athlete does not exist")
    return athlete
