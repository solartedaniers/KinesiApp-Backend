from collections.abc import Callable
from dataclasses import dataclass

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.athletes.profile_records import existing_athlete
from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.athlete import AthleteProfile
from app.models.user import UserRole
from app.repositories.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class AthletePage:
    athletes: list[AthleteProfile]
    # Lo dejo en None cuando no quedan más fichas después de esta página
    last_id: int | None


class AthleteDirectory:
    """Muestro fichas según quién pregunta: la propia, las de los deportistas de un coach o todas para el admin."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def get_visible(self, principal: Principal, athlete_id: int) -> AthleteProfile:
        async with self._uow_factory() as uow:
            athlete = await existing_athlete(uow, athlete_id)
        allowed = (
            principal.role == UserRole.ADMIN
            or (principal.role == UserRole.ATHLETE and athlete.user_id == principal.user_id)
            or (principal.role == UserRole.COACH and athlete.coach_id == principal.user_id)
        )
        if not allowed:
            raise DomainError(ErrorReason.ERROR_REASON_FORBIDDEN, "You cannot see this athlete")
        return athlete

    async def list_coached(self, coach_id: int) -> list[AthleteProfile]:
        async with self._uow_factory() as uow:
            return await uow.athletes.list_with_account_by_coach(coach_id)

    async def list(self, after_id: int, limit: int) -> AthletePage:
        async with self._uow_factory() as uow:
            # Pido una de más para saber si hay otra página sin contar toda la tabla
            athletes = await uow.athletes.list_after(after_id, limit + 1)
        has_more = len(athletes) > limit
        athletes = athletes[:limit]
        return AthletePage(athletes, athletes[-1].id if has_more else None)
