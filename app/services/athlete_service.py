from app.core.exceptions import ConflictException, NotFoundException
from app.models.athlete import AthleteProfile
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

    def _create_for_user(self, user_id: int, data: AthleteProfileBase) -> AthleteProfile:
        if self._repository.get_by_user_id(user_id) is not None:
            raise ConflictException(f"El usuario '{user_id}' ya tiene un perfil de deportista")
        # model_dump(exclude) porque AthleteProfileCreate agrega user_id como campo propio
        profile = AthleteProfile(user_id=user_id, **data.model_dump(exclude={"user_id"}))
        return self._repository.add(profile)
