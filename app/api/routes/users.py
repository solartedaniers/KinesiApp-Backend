from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.avatar import AvatarUpload
from app.services.avatar_storage import AvatarStorage
from app.services.object_storage_factory import get_avatar_storage
from app.schemas.user import (
    UserCreate,
    UserProfileUpdate,
    UserRead,
    UserRoleUpdate,
    UserStatusUpdate,
    VideoConsentGrant,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _get_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(UserRepository(db))


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def create_user(data: UserCreate, service: UserService = Depends(_get_service)) -> UserRead:
    # Alta por un admin (antes era pública y saltaba la verificación). La cuenta queda sin verificar:
    # su dueño la activa con el código que pide al iniciar sesión. El registro público es /auth/register
    return service.create_user(data)


# /me va antes que /{user_id}: la cuenta propia la edita cualquier rol autenticado
@router.patch("/me", response_model=UserRead)
def update_my_profile(
    data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(_get_service),
) -> UserRead:
    return service.update_profile(current_user, data)


@router.put("/me/avatar", response_model=UserRead)
def upload_my_avatar(
    data: AvatarUpload,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(_get_service),
    avatars: AvatarStorage = Depends(get_avatar_storage),
) -> UserRead:
    # Sube al bucket de imágenes, guarda la URL y recién entonces borra la foto anterior
    return avatars.replace(current_user.avatar_url, data, lambda url: service.set_avatar(current_user, url))


@router.delete("/me/avatar", response_model=UserRead)
def delete_my_avatar(
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(_get_service),
    avatars: AvatarStorage = Depends(get_avatar_storage),
) -> UserRead:
    return avatars.replace(current_user.avatar_url, None, lambda url: service.set_avatar(current_user, url))


@router.post("/me/video-consent", response_model=UserRead)
def grant_my_video_consent(
    data: VideoConsentGrant,
    # Sólo quien sube videos: el deportista, o el coach por sus gestionados
    current_user: User = Depends(require_roles(UserRole.ATHLETE, UserRole.COACH)),
    service: UserService = Depends(_get_service),
) -> UserRead:
    return service.grant_video_consent(current_user, data.version)


# GET queda restringido a ADMIN: listar/consultar cuentas es gestión global del sistema
@router.get("/{user_id}", response_model=UserRead, dependencies=[Depends(require_roles(UserRole.ADMIN))])
def get_user(user_id: int, service: UserService = Depends(_get_service)) -> UserRead:
    return service.get_user(user_id)


@router.get("", response_model=list[UserRead], dependencies=[Depends(require_roles(UserRole.ADMIN))])
def list_users(
    skip: int = 0, limit: int = 100, service: UserService = Depends(_get_service)
) -> list[UserRead]:
    return service.list_users(skip, limit)


@router.patch("/{user_id}/role", response_model=UserRead)
def update_user_role(
    user_id: int,
    data: UserRoleUpdate,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: UserService = Depends(_get_service),
) -> UserRead:
    return service.set_role(admin, user_id, data.role)


@router.patch("/{user_id}/status", response_model=UserRead)
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: UserService = Depends(_get_service),
) -> UserRead:
    return service.set_active(admin, user_id, data.is_active)
