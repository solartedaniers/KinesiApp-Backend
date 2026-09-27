from app.core.exceptions import NotFoundException
from app.models.athlete import AthleteProfile
from app.repositories.athlete_repository import AthleteRepository
from app.schemas.athlete import ManagedAthleteCreate, ManagedAthleteUpdate


class ManagedAthleteService:
    """CRUD de deportistas sin cuenta propia, exclusivo del coach que los creó.

    Los deportistas con cuenta (asignados por un admin) solo se listan: su ficha
    pertenece al propio deportista y un coach no puede editarla ni borrarla.
    """

    def __init__(self, repository: AthleteRepository) -> None:
        self._repository = repository

    def list_for_coach(self, coach_id: int) -> list[AthleteProfile]:
        return self._repository.list_by_coach(coach_id)

    def create(self, coach_id: int, data: ManagedAthleteCreate) -> AthleteProfile:
        return self._repository.add(AthleteProfile(coach_id=coach_id, **data.model_dump()))

    def update(self, coach_id: int, athlete_id: int, data: ManagedAthleteUpdate) -> AthleteProfile:
        profile = self._get_owned(coach_id, athlete_id)
        for field, value in data.changes().items():
            setattr(profile, field, value)
        return self._repository.add(profile)

    def delete(self, coach_id: int, athlete_id: int) -> None:
        self._repository.delete(self._get_owned(coach_id, athlete_id))

    def _get_owned(self, coach_id: int, athlete_id: int) -> AthleteProfile:
        # 404 (no 403) si no es suyo: no revela qué ids existen para otros coaches
        profile = self._repository.get_managed_by_coach(athlete_id, coach_id)
        if profile is None:
            raise NotFoundException("ManagedAthlete", athlete_id)
        return profile
