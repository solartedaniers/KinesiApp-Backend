from sqlalchemy.orm import Session

from app.models.team import Team, team_members
from app.models.user import User, UserRole
from app.repositories.base_repository import BaseRepository


class TeamRepository(BaseRepository[Team]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, Team)

    def list_by_owner(self, owner_id: int) -> list[Team]:
        return list(self._db.query(Team).filter(Team.owner_id == owner_id).order_by(Team.name).all())

    def list_all(self) -> list[Team]:
        return list(self._db.query(Team).order_by(Team.name).all())

    def get_by_owner_and_name(self, owner_id: int, name: str) -> Team | None:
        return self._db.query(Team).filter(Team.owner_id == owner_id, Team.name == name).first()

    def remove_athlete_from_other_coaches_teams(self, athlete_id: int, coach_id: int | None) -> None:
        """Al cambiar de entrenador, el deportista sale de los equipos de los demás coaches.

        No hace commit: lo confirma la operación que cambia el entrenador, en la misma transacción.
        """
        foreign_team_ids = (
            self._db.query(Team.id)
            .join(User, User.id == Team.owner_id)
            .filter(User.role == UserRole.COACH, Team.owner_id != coach_id)
        )
        self._db.execute(
            team_members.delete().where(
                team_members.c.athlete_id == athlete_id,
                team_members.c.team_id.in_(foreign_team_ids.scalar_subquery()),
            )
        )
