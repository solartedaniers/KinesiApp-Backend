from app.core.exceptions import AppException, ConflictException, ErrorCode, NotFoundException
from app.models.athlete import AthleteProfile
from app.models.user import UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.user_repository import UserRepository
from app.schemas.athlete import AthleteProfileBase, AthleteProfileCreate, AthleteProfileSelfCreate


class AthleteService:
    """Alta y consulta de perfiles de deportista. Un perfil pertenece a un único user."""

    def __init__(self, repository: AthleteRepository, user_repository: UserRepository) -> None:
        self._repository = repository
        self._user_repository = user_repository

    def create_profile(self, data: AthleteProfileCreate) -> AthleteProfile:
        # Ruta administrativa: el user_id llega en el body, así que sí hay que validar que exista
        if self._user_repository.get(data.user_id) is None:
            raise NotFoundException("User", data.user_id)
        return self._create_for_user(data.user_id, data)

    def create_own_profile(self, user_id: int, data: AthleteProfileSelfCreate) -> AthleteProfile:
        # user_id viene de get_current_user, ya validado como usuario activo: no hace falta re-consultarlo
        return self._create_for_user(user_id, data)

    def get_profile(self, athlete_id: int) -> AthleteProfile:
        profile = self._repository.get(athlete_id)
        if profile is None:
            raise NotFoundException("AthleteProfile", athlete_id)
        return profile

    def get_own_profile(self, user_id: int) -> AthleteProfile:
        profile = self._repository.get_by_user_id(user_id)
        if profile is None:
            raise NotFoundException("AthleteProfile", user_id)
        return profile

    def list_for_coach(self, coach_id: int) -> list[AthleteProfile]:
        return self._repository.list_by_coach(coach_id)

    def list_all(self, skip: int = 0, limit: int = 100) -> list[AthleteProfile]:
        # Sólo para ADMIN: alimenta la pantalla de asignación de coach, que necesita ver todos los perfiles
        return self._repository.list(skip, limit)

    def assign_coach(self, athlete_id: int, coach_id: int) -> AthleteProfile:
        # Operación de admin: valida que el "coach" exista y realmente tenga rol COACH
        profile = self.get_profile(athlete_id)
        coach = self._user_repository.get(coach_id)
        if coach is None:
            raise NotFoundException("User", coach_id)
        if coach.role != UserRole.COACH:
            raise AppException(
                f"User '{coach_id}' does not have the coach role", code=ErrorCode.INVALID_ROLE_ASSIGNMENT
            )

        profile.coach_id = coach_id
        return self._repository.add(profile)

    def _create_for_user(self, user_id: int, data: AthleteProfileBase) -> AthleteProfile:
        if self._repository.get_by_user_id(user_id) is not None:
            raise ConflictException(
                f"User '{user_id}' already has an athlete profile", code=ErrorCode.PROFILE_ALREADY_EXISTS
            )
        # model_dump(exclude) porque AthleteProfileCreate agrega user_id como campo propio
        profile = AthleteProfile(user_id=user_id, **data.model_dump(exclude={"user_id"}))
        return self._repository.add(profile)
