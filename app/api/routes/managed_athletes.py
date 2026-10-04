from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.schemas.athlete import AthleteProfileRead, ManagedAthleteCreate, ManagedAthleteUpdate
from app.schemas.avatar import AvatarUpload
from app.services.avatar_storage import AvatarStorage
from app.services.object_storage_factory import get_avatar_storage
from app.services.managed_athlete_service import ManagedAthleteService

router = APIRouter(prefix="/coach/athletes", tags=["coach-athletes"])

# Todo el router es exclusivo de COACH: el coach autenticado es siempre el dueño
_require_coach = require_roles(UserRole.COACH)


def _get_service(db: Session = Depends(get_db)) -> ManagedAthleteService:
    return ManagedAthleteService(AthleteRepository(db))


@router.get("", response_model=list[AthleteProfileRead])
def list_my_athletes(
    coach: User = Depends(_require_coach),
    service: ManagedAthleteService = Depends(_get_service),
) -> list[AthleteProfileRead]:
    return service.list_for_coach(coach.id)


@router.post("", response_model=AthleteProfileRead, status_code=status.HTTP_201_CREATED)
def create_managed_athlete(
    data: ManagedAthleteCreate,
    coach: User = Depends(_require_coach),
    service: ManagedAthleteService = Depends(_get_service),
) -> AthleteProfileRead:
    return service.create(coach.id, data)


@router.patch("/{athlete_id}", response_model=AthleteProfileRead)
def update_managed_athlete(
    athlete_id: int,
    data: ManagedAthleteUpdate,
    coach: User = Depends(_require_coach),
    service: ManagedAthleteService = Depends(_get_service),
) -> AthleteProfileRead:
    return service.update(coach.id, athlete_id, data)


@router.delete("/{athlete_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_managed_athlete(
    athlete_id: int,
    coach: User = Depends(_require_coach),
    service: ManagedAthleteService = Depends(_get_service),
    avatars: AvatarStorage = Depends(get_avatar_storage),
) -> None:
    avatar_url = service.get_owned(coach.id, athlete_id).avatar_url
    service.delete(coach.id, athlete_id)
    # Después de borrar la fila: si falla, sólo queda un objeto huérfano
    if avatar_url is not None:
        avatars.delete(avatar_url)


@router.put("/{athlete_id}/avatar", response_model=AthleteProfileRead)
def upload_managed_athlete_avatar(
    athlete_id: int,
    data: AvatarUpload,
    coach: User = Depends(_require_coach),
    service: ManagedAthleteService = Depends(_get_service),
    avatars: AvatarStorage = Depends(get_avatar_storage),
) -> AthleteProfileRead:
    previous = service.get_owned(coach.id, athlete_id).avatar_url
    return avatars.replace(previous, data, lambda url: service.set_avatar(coach.id, athlete_id, url))


@router.delete("/{athlete_id}/avatar", response_model=AthleteProfileRead)
def delete_managed_athlete_avatar(
    athlete_id: int,
    coach: User = Depends(_require_coach),
    service: ManagedAthleteService = Depends(_get_service),
    avatars: AvatarStorage = Depends(get_avatar_storage),
) -> AthleteProfileRead:
    previous = service.get_owned(coach.id, athlete_id).avatar_url
    return avatars.replace(previous, None, lambda url: service.set_avatar(coach.id, athlete_id, url))
