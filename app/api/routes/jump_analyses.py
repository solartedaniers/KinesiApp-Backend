from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import get_db, get_session_factory
from app.core.security import get_current_user, require_roles
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JumpAnalysisCreate, JumpAnalysisRead, JumpAnalysisResultIngest
from app.services.jump_analysis_processor import JumpAnalysisProcessor, JumpVideoAnalyzer
from app.services.jump_analysis_service import JumpAnalysisService
from app.services.jump_video_storage import JumpVideoStorage

router = APIRouter(prefix="/jump-analyses", tags=["jump-analyses"])


def _get_service(db: Session = Depends(get_db)) -> JumpAnalysisService:
    return JumpAnalysisService(
        JumpAnalysisRepository(db),
        AthleteRepository(db),
        JumpVideoStorage(settings.VIDEO_UPLOAD_DIR, settings.MAX_VIDEO_UPLOAD_BYTES),
    )


def _get_processor(
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> JumpAnalysisProcessor:
    return JumpAnalysisProcessor(
        session_factory, JumpVideoAnalyzer(settings.RISK_SAFE_KNEE_FLEXION_DEG)
    )


@router.post("", response_model=JumpAnalysisRead, status_code=status.HTTP_201_CREATED)
def create_analysis(
    data: JumpAnalysisCreate,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
) -> JumpAnalysisRead:
    return service.create_analysis(current_user, data)


@router.post("/upload", response_model=JumpAnalysisRead, status_code=status.HTTP_202_ACCEPTED)
def upload_video(
    background_tasks: BackgroundTasks,
    athlete_id: int = Form(...),
    video: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
    processor: JumpAnalysisProcessor = Depends(_get_processor),
) -> JumpAnalysisRead:
    # `def` y no `async def`: la copia a disco corre en el threadpool, no en el event loop
    analysis = service.create_from_upload(current_user, athlete_id, video.file, video.content_type)
    # Corre después de enviar la respuesta: el cliente recibe 202 + PENDING al instante
    # y consulta GET /{analysis_id} hasta ver PROCESSED o FAILED
    background_tasks.add_task(processor.process, analysis.id)
    return analysis


# Antes de /{analysis_id}: si no, "team" se intentaría parsear como id
@router.get("/team", response_model=list[JumpAnalysisRead])
def list_team_analyses(
    coach: User = Depends(require_roles(UserRole.COACH)),
    service: JumpAnalysisService = Depends(_get_service),
) -> list[JumpAnalysisRead]:
    return service.list_for_coach(coach)


@router.get("/{analysis_id}", response_model=JumpAnalysisRead)
def get_analysis(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
) -> JumpAnalysisRead:
    return service.get_analysis(current_user, analysis_id)


@router.get("/by-athlete/{athlete_id}", response_model=list[JumpAnalysisRead])
def list_by_athlete(
    athlete_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
) -> list[JumpAnalysisRead]:
    return service.list_by_athlete(current_user, athlete_id)


@router.post("/{analysis_id}/results", response_model=JumpAnalysisRead)
def ingest_result(
    analysis_id: int,
    result: JumpAnalysisResultIngest,
    service: JumpAnalysisService = Depends(_get_service),
) -> JumpAnalysisRead:
    # Endpoint que el pipeline de IA llama al terminar de procesar el video del salto.
    # No lleva token de usuario KinesiApp: es un webhook de un sistema interno, no una
    # sesión con rol. ponytail: sin auth de servicio (API key/mTLS) todavía; agregar si
    # este endpoint queda expuesto fuera de la red interna
    return service.ingest_result(analysis_id, result)
