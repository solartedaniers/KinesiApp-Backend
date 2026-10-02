import mimetypes

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import get_db, get_session_factory
from app.core.security import (
    create_video_access_token,
    get_current_user,
    require_roles,
    require_service_api_key,
    verify_video_access_token,
)
from app.models.jump_analysis import MovementType
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JumpAnalysisRead, JumpAnalysisResultIngest, VideoAccessRead
from app.services.jump_analysis_processor import JumpAnalysisProcessor, JumpVideoAnalyzer
from app.services.jump_video_analyzer_factory import get_jump_video_analyzer
from app.services.jump_analysis_service import JumpAnalysisService
from app.services.jump_video_storage import JumpVideoStorage

router = APIRouter(prefix="/jump-analyses", tags=["jump-analyses"])


def _get_service(db: Session = Depends(get_db)) -> JumpAnalysisService:
    return JumpAnalysisService(
        JumpAnalysisRepository(db),
        AthleteRepository(db),
        JumpVideoStorage(settings.VIDEO_UPLOAD_DIR, settings.MAX_VIDEO_UPLOAD_BYTES),
        settings.VIDEO_CONSENT_VERSION,
    )


def _get_processor(
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    analyzer: JumpVideoAnalyzer = Depends(get_jump_video_analyzer),
) -> JumpAnalysisProcessor:
    return JumpAnalysisProcessor(session_factory, analyzer)


@router.post("/upload", response_model=JumpAnalysisRead, status_code=status.HTTP_202_ACCEPTED)
def upload_video(
    background_tasks: BackgroundTasks,
    athlete_id: int = Form(...),
    # Opcional para no romper clientes anteriores: sin él, se asume salto
    movement_type: MovementType = Form(MovementType.JUMP),
    video: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
    processor: JumpAnalysisProcessor = Depends(_get_processor),
) -> JumpAnalysisRead:
    # `def` y no `async def`: la copia a disco corre en el threadpool, no en el event loop
    analysis = service.create_from_upload(
        current_user, athlete_id, movement_type, video.file, video.content_type
    )
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


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
) -> None:
    service.delete_analysis(current_user, analysis_id)


@router.get("/{analysis_id}/video-access", response_model=VideoAccessRead)
def get_video_access(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
) -> VideoAccessRead:
    # Mismo control de acceso que GET /{analysis_id}; el token sólo abre este video
    service.get_analysis(current_user, analysis_id)
    token, expires_at = create_video_access_token(analysis_id)
    return VideoAccessRead(token=token, expires_at=expires_at)


@router.get("/{analysis_id}/video", response_class=FileResponse)
def stream_video(
    analysis_id: int,
    token: str = Query(...),
    service: JumpAnalysisService = Depends(_get_service),
) -> FileResponse:
    # Token en la query (no Bearer): los reproductores de video no mandan headers,
    # en especial en Flutter web. FileResponse atiende Range: se puede adelantar el video
    verify_video_access_token(token, analysis_id)
    path = service.get_video_path(analysis_id)
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@router.get("/by-athlete/{athlete_id}", response_model=list[JumpAnalysisRead])
def list_by_athlete(
    athlete_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(_get_service),
) -> list[JumpAnalysisRead]:
    return service.list_by_athlete(current_user, athlete_id)


@router.post(
    "/{analysis_id}/results",
    response_model=JumpAnalysisRead,
    dependencies=[Depends(require_service_api_key)],
)
def ingest_result(
    analysis_id: int,
    result: JumpAnalysisResultIngest,
    service: JumpAnalysisService = Depends(_get_service),
) -> JumpAnalysisRead:
    # Lo llama un proceso interno (pipeline de IA), no una persona: se autentica con
    # la API key de servicio del header X-Service-Api-Key, no con el JWT de usuarios
    return service.ingest_result(analysis_id, result)
