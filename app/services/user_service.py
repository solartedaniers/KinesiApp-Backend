from passlib.context import CryptContext

from app.core.exceptions import ConflictException, NotFoundException
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserService:
    """Reglas de negocio de usuarios: nunca persiste una contraseña en texto plano."""

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def create_user(self, data: UserCreate) -> User:
        if self._repository.get_by_email(data.email) is not None:
            raise ConflictException(f"El email '{data.email}' ya está registrado")

        user = User(
            email=data.email,
            hashed_password=_pwd_context.hash(data.password),
            full_name=data.full_name,
        )
        return self._repository.add(user)

    def get_user(self, user_id: int) -> User:
        user = self._repository.get(user_id)
        if user is None:
            raise NotFoundException("User", user_id)
        return user

    def list_users(self, skip: int = 0, limit: int = 100) -> list[User]:
        return self._repository.list(skip, limit)
