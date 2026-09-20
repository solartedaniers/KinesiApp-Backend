from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.user_repository import UserRepository
from app.schemas.athlete import (
    AthleteProfileCreate,
    AthleteProfileRead,
    AthleteProfileSelfCreate,
    CoachAssignment,
)
from app.services.athlete_service import AthleteService

router = APIRouter(prefix="/athletes", tags=["athletes"])


def _get_service(db: Session = Depends(get_db)) -> AthleteService:
    return AthleteService(AthleteRepository(db), UserRepository(db))


# Rutas estáticas (/me, /coached) van antes de /{athlete_id}, si no FastAPI intenta
# parsear "me"/"coached" como el int del path param y responde 422 en vez de resolverlas
@router.post("/me", response_model=AthleteProfileRead, status_code=status.HTTP_201_CREATED)
def create_my_profile(
    data: AthleteProfileSelfCreate,
    current_user: User = Depends(require_roles(UserRole.ATHLETE)),
    service: AthleteService = Depends(_get_service),
) -> AthleteProfileRead:
    return service.create_own_profile(current_user.id, data)


@router.get("/me", response_model=AthleteProfileRead)
def get_my_profile(
    current_user: User = Depends(require_roles(UserRole.ATHLETE)),
    service: AthleteService = Depends(_get_service),
) -> AthleteProfileRead:
    return service.get_own_profile(current_user.id)


@router.get("/coached", response_model=list[AthleteProfileRead])
def list_coached_athletes(
    current_user: User = Depends(require_roles(UserRole.COACH)),
    service: AthleteService = Depends(_get_service),
) -> list[AthleteProfileRead]:
    return service.list_for_coach(current_user.id)


@router.get("", response_model=list[AthleteProfileRead], dependencies=[Depends(require_roles(UserRole.ADMIN))])
def list_athletes(
    skip: int = 0, limit: int = 100, service: AthleteService = Depends(_get_service)
) -> list[AthleteProfileRead]:
    return service.list_all(skip, limit)


@router.post("", response_model=AthleteProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    data: AthleteProfileCreate, service: AthleteService = Depends(_get_service)
) -> AthleteProfileRead:
    return service.create_profile(data)


@router.get("/{athlete_id}", response_model=AthleteProfileRead)
def get_profile(athlete_id: int, service: AthleteService = Depends(_get_service)) -> AthleteProfileRead:
    return service.get_profile(athlete_id)


@router.patch(
    "/{athlete_id}/coach",
    response_model=AthleteProfileRead,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def assign_coach(
    athlete_id: int, data: CoachAssignment, service: AthleteService = Depends(_get_service)
) -> AthleteProfileRead:
    return service.assign_coach(athlete_id, data.coach_id)
