from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.user_repository import UserRepository
from app.schemas.athlete import AthleteProfileCreate, AthleteProfileRead, AthleteProfileSelfCreate
from app.services.athlete_service import AthleteService

router = APIRouter(prefix="/athletes", tags=["athletes"])


def _get_service(db: Session = Depends(get_db)) -> AthleteService:
    return AthleteService(AthleteRepository(db), UserRepository(db))


# Rutas /me: van antes de /{athlete_id} para que "me" no se intente parsear como int
@router.post("/me", response_model=AthleteProfileRead, status_code=status.HTTP_201_CREATED)
def create_my_profile(
    data: AthleteProfileSelfCreate,
    current_user: User = Depends(get_current_user),
    service: AthleteService = Depends(_get_service),
) -> AthleteProfileRead:
    return service.create_own_profile(current_user.id, data)


@router.get("/me", response_model=AthleteProfileRead)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    service: AthleteService = Depends(_get_service),
) -> AthleteProfileRead:
    return service.get_own_profile(current_user.id)


@router.post("", response_model=AthleteProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    data: AthleteProfileCreate, service: AthleteService = Depends(_get_service)
) -> AthleteProfileRead:
    return service.create_profile(data)


@router.get("/{athlete_id}", response_model=AthleteProfileRead)
def get_profile(athlete_id: int, service: AthleteService = Depends(_get_service)) -> AthleteProfileRead:
    return service.get_profile(athlete_id)
