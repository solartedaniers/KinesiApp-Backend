from sqlalchemy.orm import Session

from app.models.jump_analysis import JumpAnalysis
from app.repositories.base_repository import BaseRepository


class JumpAnalysisRepository(BaseRepository[JumpAnalysis]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, JumpAnalysis)

    def list_by_athlete(self, athlete_id: int) -> list[JumpAnalysis]:
        return list(
            self._db.query(JumpAnalysis).filter(JumpAnalysis.athlete_id == athlete_id).all()
        )
