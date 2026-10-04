from app.core.exceptions import AppException, ConflictException, ErrorCode, NotFoundException
from app.models.athlete import AthleteProfile
from app.models.team import Team
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.team_repository import TeamRepository


class TeamService:
    """Equipos: el coach organiza a sus deportistas; el admin ve y administra todos.

    Quién puede pertenecer a un equipo lo decide su dueño, no quien edita: en el equipo de un coach
    sólo entran deportistas de ese coach (con cuenta o gestionados), aunque lo edite un admin.
    """

    def __init__(self, repository: TeamRepository, athlete_repository: AthleteRepository) -> None:
        self._repository = repository
        self._athletes = athlete_repository

    def list_for(self, user: User) -> list[Team]:
        return self._repository.list_all() if user.role == UserRole.ADMIN else self._repository.list_by_owner(user.id)

    def create(self, user: User, name: str) -> Team:
        self._require_unique_name(user.id, name)
        return self._repository.add(Team(owner_id=user.id, name=name))

    def get(self, user: User, team_id: int) -> Team:
        team = self._repository.get(team_id)
        # 404 (no 403) para equipos ajenos: no revela qué ids existen
        if team is None or (user.role != UserRole.ADMIN and team.owner_id != user.id):
            raise NotFoundException("Team", team_id)
        return team

    def rename(self, user: User, team_id: int, name: str) -> Team:
        team = self.get(user, team_id)
        if name != team.name:
            self._require_unique_name(team.owner_id, name)
            team.name = name
        return self._repository.add(team)

    def delete(self, user: User, team_id: int) -> None:
        # Borra el grupo, nunca a los deportistas
        self._repository.delete(self.get(user, team_id))

    def add_member(self, user: User, team_id: int, athlete_id: int) -> Team:
        team = self.get(user, team_id)
        athlete = self._athletes.get(athlete_id)
        if athlete is None:
            raise NotFoundException("AthleteProfile", athlete_id)
        if not self._can_join(team, athlete):
            raise AppException("The athlete is not coached by the team owner", code=ErrorCode.INVALID_TEAM_MEMBER)
        if athlete not in team.athletes:
            team.athletes.append(athlete)
        return self._repository.add(team)

    def remove_member(self, user: User, team_id: int, athlete_id: int) -> Team:
        team = self.get(user, team_id)
        team.athletes = [athlete for athlete in team.athletes if athlete.id != athlete_id]
        return self._repository.add(team)

    @staticmethod
    def _can_join(team: Team, athlete: AthleteProfile) -> bool:
        return team.owner.role == UserRole.ADMIN or athlete.coach_id == team.owner_id

    def _require_unique_name(self, owner_id: int, name: str) -> None:
        if self._repository.get_by_owner_and_name(owner_id, name) is not None:
            raise ConflictException(f"A team named '{name}' already exists", code=ErrorCode.TEAM_NAME_TAKEN)
