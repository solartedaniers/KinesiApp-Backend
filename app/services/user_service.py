from datetime import datetime, timezone

from app.core.exceptions import ConflictException, ErrorCode, ForbiddenException, NotFoundException
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

    def set_role(self, admin: User, user_id: int, role: UserRole) -> User:
        # Único mecanismo para volverse COACH/ADMIN: un admin ya autenticado lo asigna
        user = self._get_other_user(admin, user_id)
        # Un coach que deja de serlo dejaría huérfanos a sus deportistas gestionados
        if user.role == UserRole.COACH and role != UserRole.COACH and user.coached_athletes:
            raise ConflictException(
                "Reassign the coach's athletes before changing the role", code=ErrorCode.COACH_HAS_ATHLETES
            )
        user.role = role
        return self._repository.add(user)

    def promote_to_admin(self, user_id: int) -> User:
        """Arranque del sistema desde la CLI (create-admin): no hay un admin que actúe."""
        user = self.get_user(user_id)
        user.role = UserRole.ADMIN
        return self._repository.add(user)

    def set_active(self, admin: User, user_id: int, is_active: bool) -> User:
        # Desactivar no borra datos: la cuenta deja de poder iniciar sesión y renovar su sesión
        user = self._get_other_user(admin, user_id)
        user.is_active = is_active
        return self._repository.add(user)

    def _get_other_user(self, admin: User, user_id: int) -> User:
        # Ningún admin se cambia el rol ni se desactiva a sí mismo: evita quedarse sin administradores
        if user_id == admin.id:
            raise ForbiddenException("You cannot modify your own account", code=ErrorCode.CANNOT_MODIFY_OWN_ACCOUNT)
        return self.get_user(user_id)

    def update_profile(self, user: User, data: UserProfileUpdate) -> User:
        user.full_name = data.full_name
        return self._repository.add(user)

    def set_avatar(self, user: User, avatar_url: str | None) -> User:
        user.avatar_url = avatar_url
        return self._repository.add(user)

    def grant_video_consent(self, user: User, version: int) -> User:
        user.video_consent_given_at = datetime.now(timezone.utc)
        user.video_consent_version = version
        return self._repository.add(user)
