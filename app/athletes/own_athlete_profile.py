from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.athletes.inputs import BiometricsInput, BiometricsUpdateInput
from app.athletes.profile_records import existing_athlete, open_profile
from app.core.domain_error import DomainError
from app.models.athlete import AthleteProfile
from app.repositories.unit_of_work import UnitOfWork


class OwnAthleteProfile:
    """Manejo la ficha del deportista que llama: la crea en el onboarding y después la consulta y la edita."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def create(self, user_id: int, biometrics: BiometricsInput) -> AthleteProfile:
        async with self._uow_factory() as uow:
            return await open_profile(uow, user_id, biometrics)

    async def get(self, user_id: int) -> AthleteProfile:
        async with self._uow_factory() as uow:
            return await _own_profile(uow, user_id)

    async def update(self, user_id: int, biometrics: BiometricsUpdateInput) -> AthleteProfile:
        async with self._uow_factory() as uow:
            profile = await _own_profile(uow, user_id)
            for field, value in biometrics.changes().items():
                setattr(profile, field, value)
            await uow.commit()
            return await existing_athlete(uow, profile.id)


async def _own_profile(uow: UnitOfWork, user_id: int) -> AthleteProfile:
    profile = await uow.athletes.get_by_user_id(user_id)
    if profile is None:
        # El frontend lo trata como "falta el onboarding", no como un fallo
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The athlete profile has not been created yet")
    return profile
