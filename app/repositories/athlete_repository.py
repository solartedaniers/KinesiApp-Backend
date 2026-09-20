from sqlalchemy.orm import Session

from app.models.athlete import AthleteProfile
from app.repositories.base_repository import BaseRepository


class AthleteRepository(BaseRepository[AthleteProfile]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, AthleteProfile)

    def get_by_user_id(self, user_id: int) -> AthleteProfile | None:
        return self._db.query(AthleteProfile).filter(AthleteProfile.user_id == user_id).first()

    def list_by_coach(self, coach_id: int) -> list[AthleteProfile]:
        return list(
            self._db.query(AthleteProfile).filter(AthleteProfile.coach_id == coach_id).all()
        )
