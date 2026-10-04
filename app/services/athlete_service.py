from app.core.exceptions import AppException, ConflictException, ErrorCode, NotFoundException
from app.models.athlete import AthleteProfile
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.user_repository import UserRepository
from app.schemas.athlete import (
    AthleteProfileBase,
    AthleteProfileCreate,
    AthleteProfileSelfCreate,
    AthleteProfileUpdate,
)


class AthleteService:
    """Alta y consulta de perfiles de deportista. Un perfil pertenece a un único user."""

    def __init__(
        self, repository: AthleteRepository, user_repository: UserRepository, team_repository: TeamRepository
    ) -> None:
        self._repository = repository
        self._user_repository = user_repository
        self._team_repository = team_repository

    def create_profile(self, data: AthleteProfileCreate) -> AthleteProfile:
        # Ruta administrativa: el user_id llega en el body, así que sí hay que validar que exista
        user = self._user_repository.get(data.user_id)
        if user is None:
            raise NotFoundException("User", data.user_id)
        # La ficha biométrica es de un deportista: un coach o un admin no tienen
        if user.role != UserRole.ATHLETE:
            raise AppException(
                f"User '{data.user_id}' does not have the athlete role", code=ErrorCode.INVALID_ROLE_ASSIGNMENT
            )
        return self._create_for_user(data.user_id, data)

    def create_own_profile(self, user_id: int, data: AthleteProfileSelfCreate) -> AthleteProfile:
        # user_id viene de get_current_user, ya validado como usuario activo: no hace falta re-consultarlo
        return self._create_for_user(user_id, data)

    def get_profile(self, athlete_id: int) -> AthleteProfile:
        profile = self._repository.get(athlete_id)
        if profile is None:
            raise NotFoundException("AthleteProfile", athlete_id)
        return profile

    def get_profile_for(self, current_user: User, athlete_id: int) -> AthleteProfile:
        """La ficha la ven el propio deportista, su coach asignado y un admin; para el resto, 404."""
        profile = self._repository.get(athlete_id)
        allowed = profile is not None and (
            current_user.role == UserRole.ADMIN
            or (current_user.role == UserRole.ATHLETE and profile.user_id == current_user.id)
            or (current_user.role == UserRole.COACH and profile.coach_id == current_user.id)
        )
        if not allowed:
            raise NotFoundException("AthleteProfile", athlete_id)
        return profile

    def get_own_profile(self, user_id: int) -> AthleteProfile:
        profile = self._repository.get_by_user_id(user_id)
        if profile is None:
            raise NotFoundException("AthleteProfile", user_id)
        return profile

    def update_own_profile(self, user_id: int, data: AthleteProfileUpdate) -> AthleteProfile:
        profile = self.get_own_profile(user_id)
        for field, value in data.changes().items():
            setattr(profile, field, value)
        return self._repository.add(profile)

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
        # Sus equipos con el coach anterior ya no le corresponden; los de un admin se conservan
        self._team_repository.remove_athlete_from_other_coaches_teams(athlete_id, coach_id)
        return self._repository.add(profile)

    def _create_for_user(self, user_id: int, data: AthleteProfileBase) -> AthleteProfile:
        if self._repository.get_by_user_id(user_id) is not None:
            raise ConflictException(
                f"User '{user_id}' already has an athlete profile", code=ErrorCode.PROFILE_ALREADY_EXISTS
            )
        # model_dump(exclude) porque AthleteProfileCreate agrega user_id como campo propio
        profile = AthleteProfile(user_id=user_id, **data.model_dump(exclude={"user_id"}))
        return self._repository.add(profile)
