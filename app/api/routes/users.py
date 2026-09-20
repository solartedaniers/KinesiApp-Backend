from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_roles
from app.models.user import UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserRead, UserRoleUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _get_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(UserRepository(db))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, service: UserService = Depends(_get_service)) -> UserRead:
    # Alta pública heredada de antes del módulo de auth; sigue abierta por compatibilidad.
    # El flujo "real" con verificación de email es /auth/register
    return service.create_user(data)


# GET queda restringido a ADMIN: listar/consultar cuentas es gestión global del sistema
@router.get("/{user_id}", response_model=UserRead, dependencies=[Depends(require_roles(UserRole.ADMIN))])
def get_user(user_id: int, service: UserService = Depends(_get_service)) -> UserRead:
    return service.get_user(user_id)


@router.get("", response_model=list[UserRead], dependencies=[Depends(require_roles(UserRole.ADMIN))])
def list_users(
    skip: int = 0, limit: int = 100, service: UserService = Depends(_get_service)
) -> list[UserRead]:
    return service.list_users(skip, limit)


@router.patch(
    "/{user_id}/role", response_model=UserRead, dependencies=[Depends(require_roles(UserRole.ADMIN))]
)
def update_user_role(
    user_id: int, data: UserRoleUpdate, service: UserService = Depends(_get_service)
) -> UserRead:
    return service.set_role(user_id, data.role)
