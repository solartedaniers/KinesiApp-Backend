from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JumpAnalysisCreate, JumpAnalysisRead, JumpAnalysisResultIngest
from app.services.jump_analysis_service import JumpAnalysisService

router = APIRouter(prefix="/jump-analyses", tags=["jump-analyses"])


def _get_service(db: Session = Depends(get_db)) -> JumpAnalysisService:
    return JumpAnalysisService(JumpAnalysisRepository(db), AthleteRepository(db))


@router.post("", response_model=JumpAnalysisRead, status_code=status.HTTP_201_CREATED)
def create_analysis(
    data: JumpAnalysisCreate, service: JumpAnalysisService = Depends(_get_service)
) -> JumpAnalysisRead:
    return service.create_analysis(data)


@router.get("/{analysis_id}", response_model=JumpAnalysisRead)
def get_analysis(analysis_id: int, service: JumpAnalysisService = Depends(_get_service)) -> JumpAnalysisRead:
    return service.get_analysis(analysis_id)


@router.get("/by-athlete/{athlete_id}", response_model=list[JumpAnalysisRead])
def list_by_athlete(
    athlete_id: int, service: JumpAnalysisService = Depends(_get_service)
) -> list[JumpAnalysisRead]:
    return service.list_by_athlete(athlete_id)


@router.post("/{analysis_id}/results", response_model=JumpAnalysisRead)
def ingest_result(
    analysis_id: int,
    result: JumpAnalysisResultIngest,
    service: JumpAnalysisService = Depends(_get_service),
) -> JumpAnalysisRead:
    # Endpoint que el pipeline de IA llama al terminar de procesar el video del salto
    return service.ingest_result(analysis_id, result)
