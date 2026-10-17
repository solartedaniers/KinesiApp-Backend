from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.admin.user_directory import existing_user
from app.athletes.inputs import BiometricsInput
from app.athletes.profile_records import existing_athlete, open_profile
from app.core.domain_error import DomainError
from app.models.athlete import AthleteProfile
from app.models.user import UserRole
from app.repositories.unit_of_work import UnitOfWork


class AthleteAdministration:
    """Le dejo al admin crear la ficha de una cuenta de deportista y asignarle su coach."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def create_for_user(self, user_id: int, biometrics: BiometricsInput) -> AthleteProfile:
        async with self._uow_factory() as uow:
            user = await existing_user(uow, user_id)
            # No le creo ficha a un coach ni a un admin: la ficha biométrica es solo de deportistas
            if user.role != UserRole.ATHLETE:
                raise DomainError(ErrorReason.ERROR_REASON_INVALID_ROLE_ASSIGNMENT, "The account is not an athlete")
            return await open_profile(uow, user_id, biometrics)

    async def assign_coach(self, athlete_id: int, coach_id: int) -> AthleteProfile:
        async with self._uow_factory() as uow:
            athlete = await existing_athlete(uow, athlete_id)
            coach = await existing_user(uow, coach_id)
            if coach.role != UserRole.COACH:
                raise DomainError(ErrorReason.ERROR_REASON_INVALID_ROLE_ASSIGNMENT, "The account is not a coach")
            athlete.coach_id = coach_id
            # Lo saco de los equipos del coach anterior, que ya no le corresponden; los de un admin los conservo
            await uow.teams.remove_athlete_from_other_coaches_teams(athlete_id, coach_id)
            await uow.commit()
            return await existing_athlete(uow, athlete_id)
