from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.team import Team, team_members
from app.models.user import User, UserRole
from app.repositories.async_base_repository import AsyncBaseRepository


def _with_members() -> Select[tuple[Team]]:
    # Cargo dueño y miembros de entrada: los necesito para athlete_ids y para decidir quién puede entrar
    return select(Team).options(selectinload(Team.owner), selectinload(Team.athletes))


class AsyncTeamRepository(AsyncBaseRepository[Team]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Team)

    async def get_team(self, team_id: int) -> Team | None:
        query = _with_members().where(Team.id == team_id).execution_options(populate_existing=True)
        return await self._session.scalar(query)

    async def list_by_owner(self, owner_id: int) -> list[Team]:
        return list(await self._session.scalars(_with_members().where(Team.owner_id == owner_id).order_by(Team.name)))

    async def list_all(self) -> list[Team]:
        return list(await self._session.scalars(_with_members().order_by(Team.name)))

    async def name_taken(self, owner_id: int, name: str) -> bool:
        query = select(Team.id).where(Team.owner_id == owner_id, Team.name == name)
        return await self._session.scalar(query) is not None

    async def remove_athlete_from_other_coaches_teams(self, athlete_id: int, coach_id: int) -> None:
        # Los equipos de un admin los conservo: solo saco al deportista de los de otros coaches
        foreign_teams = select(Team.id).join(User, User.id == Team.owner_id).where(
            User.role == UserRole.COACH, Team.owner_id != coach_id
        )
        await self._session.execute(
            team_members.delete().where(team_members.c.athlete_id == athlete_id, team_members.c.team_id.in_(foreign_teams))
        )

    async def delete(self, team: Team) -> None:
        await self._session.delete(team)
