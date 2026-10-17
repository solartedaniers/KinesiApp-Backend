from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.athletes.profile_records import existing_athlete
from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.team import Team
from app.models.user import UserRole
from app.repositories.unit_of_work import UnitOfWork
from app.teams.team_catalog import visible_team


class TeamMembership:
    """Meto y saco deportistas de un equipo. Quién puede entrar lo decide el dueño del equipo, no quien lo edita."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def add(self, principal: Principal, team_id: int, athlete_id: int) -> Team:
        async with self._uow_factory() as uow:
            team = await visible_team(uow, principal, team_id)
            athlete = await existing_athlete(uow, athlete_id)
            # En el equipo de un coach solo entran sus deportistas, aunque lo edite un admin
            if team.owner.role != UserRole.ADMIN and athlete.coach_id != team.owner_id:
                raise DomainError(ErrorReason.ERROR_REASON_INVALID_TEAM_MEMBER, "The athlete is not coached by the team owner")
            if athlete_id not in team.athlete_ids:
                team.athletes.append(athlete)
                await uow.commit()
            return team

    async def remove(self, principal: Principal, team_id: int, athlete_id: int) -> Team:
        async with self._uow_factory() as uow:
            team = await visible_team(uow, principal, team_id)
            remaining = [athlete for athlete in team.athletes if athlete.id != athlete_id]
            if len(remaining) != len(team.athletes):
                team.athletes = remaining
                await uow.commit()
            return team
