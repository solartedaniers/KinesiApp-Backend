from app.core.exceptions import ConflictException, NotFoundException
from app.models.athlete import AthleteProfile
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.user_repository import UserRepository
from app.schemas.athlete import AthleteProfileCreate


class AthleteService:
    def __init__(self, repository: AthleteRepository, user_repository: UserRepository) -> None:
        self._repository = repository
        self._user_repository = user_repository

    def create_profile(self, data: AthleteProfileCreate) -> AthleteProfile:
        if self._user_repository.get(data.user_id) is None:
            raise NotFoundException("User", data.user_id)
        if self._repository.get_by_user_id(data.user_id) is not None:
            raise ConflictException(f"El usuario '{data.user_id}' ya tiene un perfil de deportista")

        profile = AthleteProfile(**data.model_dump())
        return self._repository.add(profile)

    def get_profile(self, athlete_id: int) -> AthleteProfile:
        profile = self._repository.get(athlete_id)
        if profile is None:
            raise NotFoundException("AthleteProfile", athlete_id)
        return profile
