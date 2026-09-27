from datetime import datetime, timezone

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserProfileUpdate


class UserService:
    """Reglas de negocio de usuarios: nunca persiste una contraseña en texto plano."""

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def create_user(self, data: UserCreate) -> User:
        if self._repository.get_by_email(data.email) is not None:
            raise ConflictException(
                f"Email '{data.email}' is already registered", code=ErrorCode.EMAIL_ALREADY_REGISTERED
            )

        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        return self._repository.add(user)

    def get_user(self, user_id: int) -> User:
        user = self._repository.get(user_id)
        if user is None:
            raise NotFoundException("User", user_id)
        return user

    def list_users(self, skip: int = 0, limit: int = 100) -> list[User]:
        return self._repository.list(skip, limit)

    def set_role(self, user_id: int, role: UserRole) -> User:
        # Único mecanismo para volverse COACH/ADMIN: un admin ya autenticado lo asigna
        user = self.get_user(user_id)
        user.role = role
        return self._repository.add(user)

    def update_profile(self, user: User, data: UserProfileUpdate) -> User:
        user.full_name = data.full_name
        return self._repository.add(user)

    def set_avatar(self, user: User, avatar_data_url: str | None) -> User:
        user.avatar_data_url = avatar_data_url
        return self._repository.add(user)

    def grant_video_consent(self, user: User, version: int) -> User:
        user.video_consent_given_at = datetime.now(timezone.utc)
        user.video_consent_version = version
        return self._repository.add(user)
