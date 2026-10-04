from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.team_repository import TeamRepository
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate
from app.services.team_service import TeamService

router = APIRouter(prefix="/teams", tags=["teams"])

# Entrenadores (sus equipos) y administradores (todos). Un deportista nunca gestiona equipos
_require_team_manager = require_roles(UserRole.COACH, UserRole.ADMIN)


def _get_service(db: Session = Depends(get_db)) -> TeamService:
    return TeamService(TeamRepository(db), AthleteRepository(db))


@router.get("", response_model=list[TeamRead])
def list_teams(user: User = Depends(_require_team_manager), service: TeamService = Depends(_get_service)) -> list[TeamRead]:
    return service.list_for(user)


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(
    data: TeamCreate, user: User = Depends(_require_team_manager), service: TeamService = Depends(_get_service)
) -> TeamRead:
    return service.create(user, data.name)


@router.get("/{team_id}", response_model=TeamRead)
def get_team(team_id: int, user: User = Depends(_require_team_manager), service: TeamService = Depends(_get_service)) -> TeamRead:
    return service.get(user, team_id)


@router.patch("/{team_id}", response_model=TeamRead)
def rename_team(
    team_id: int,
    data: TeamUpdate,
    user: User = Depends(_require_team_manager),
    service: TeamService = Depends(_get_service),
) -> TeamRead:
    return service.rename(user, team_id, data.name)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: int, user: User = Depends(_require_team_manager), service: TeamService = Depends(_get_service)) -> None:
    service.delete(user, team_id)


@router.put("/{team_id}/athletes/{athlete_id}", response_model=TeamRead)
def add_team_member(
    team_id: int,
    athlete_id: int,
    user: User = Depends(_require_team_manager),
    service: TeamService = Depends(_get_service),
) -> TeamRead:
    # PUT idempotente: agregar dos veces al mismo deportista no lo duplica
    return service.add_member(user, team_id, athlete_id)


@router.delete("/{team_id}/athletes/{athlete_id}", response_model=TeamRead)
def remove_team_member(
    team_id: int,
    athlete_id: int,
    user: User = Depends(_require_team_manager),
    service: TeamService = Depends(_get_service),
) -> TeamRead:
    return service.remove_member(user, team_id, athlete_id)
