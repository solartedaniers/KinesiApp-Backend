from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserRead
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _get_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(UserRepository(db))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, service: UserService = Depends(_get_service)) -> UserRead:
    return service.create_user(data)


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, service: UserService = Depends(_get_service)) -> UserRead:
    return service.get_user(user_id)


@router.get("", response_model=list[UserRead])
def list_users(
    skip: int = 0, limit: int = 100, service: UserService = Depends(_get_service)
) -> list[UserRead]:
    return service.list_users(skip, limit)
