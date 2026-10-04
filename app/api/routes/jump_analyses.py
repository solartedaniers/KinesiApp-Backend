from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import get_db, get_session_factory
from app.core.exceptions import ForbiddenException
from app.core.security import (
    Uploader,
    create_video_access_token,
    create_video_upload_token,
    get_current_user,
    get_uploader,
    require_roles,
    require_service_api_key,
    verify_video_access_token,
)
from app.models.jump_analysis import MovementType
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import (
    JumpAnalysisRead,
    JumpAnalysisResultIngest,
    VideoAccessRead,
    VideoUploadTokenCreate,
    VideoUploadTokenRead,
)
from app.services.jump_analysis_processor import JumpAnalysisProcessor, JumpVideoAnalyzer
from app.services.jump_video_analyzer_factory import get_jump_video_analyzer
from app.services.jump_analysis_service import JumpAnalysisService
from app.services.jump_video_storage import JumpVideoStorage
from app.services.object_storage_factory import get_video_object_storage
from app.storage.object_storage import ObjectStorage

router = APIRouter(prefix="/jump-analyses", tags=["jump-analyses"])


def _get_video_storage(
    object_storage: ObjectStorage = Depends(get_video_object_storage),
) -> JumpVideoStorage:
    return JumpVideoStorage(object_storage, settings.MAX_VIDEO_UPLOAD_BYTES)


def get_jump_analysis_service(
    db: Session = Depends(get_db), video_storage: JumpVideoStorage = Depends(_get_video_storage)
) -> JumpAnalysisService:
    return JumpAnalysisService(
        JumpAnalysisRepository(db),
        AthleteRepository(db),
        video_storage,
        settings.VIDEO_CONSENT_VERSION,
    )


def _get_processor(
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    analyzer: JumpVideoAnalyzer = Depends(get_jump_video_analyzer),
    video_storage: JumpVideoStorage = Depends(_get_video_storage),
) -> JumpAnalysisProcessor:
    return JumpAnalysisProcessor(session_factory, analyzer, video_storage)


@router.post("/upload", response_model=JumpAnalysisRead, status_code=status.HTTP_202_ACCEPTED)
def upload_video(
    background_tasks: BackgroundTasks,
    athlete_id: int = Form(...),
    # Opcional para no romper clientes anteriores: sin él, se asume salto
    movement_type: MovementType = Form(MovementType.JUMP),
    video: UploadFile = File(...),
    uploader: Uploader = Depends(get_uploader),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
    processor: JumpAnalysisProcessor = Depends(_get_processor),
) -> JumpAnalysisRead:
    # Un token de subida sólo vale para el deportista para el que se emitió
    if uploader.allowed_athlete_id is not None and uploader.allowed_athlete_id != athlete_id:
        raise ForbiddenException("The upload token was issued for another athlete")
    # `def` y no `async def`: la subida al bucket corre en el threadpool, no en el event loop
    analysis = service.create_from_upload(
        uploader.user, athlete_id, movement_type, video.file, video.content_type
    )
    # Corre después de enviar la respuesta: el cliente recibe 202 + PENDING al instante
    # y consulta GET /{analysis_id} hasta ver PROCESSED o FAILED
    background_tasks.add_task(processor.process, analysis.id)
    return analysis


@router.post("/upload-token", response_model=VideoUploadTokenRead)
def create_upload_token(
    data: VideoUploadTokenCreate,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
) -> VideoUploadTokenRead:
    # Mismas reglas que la subida (rol, dueño o coach del gestionado, consentimiento) antes de emitir
    # nada: el error sale aquí, no después de que el navegador mandó todo el video
    service.authorize_upload(current_user, data.athlete_id)
    token, expires_at = create_video_upload_token(current_user.id, data.athlete_id)
    return VideoUploadTokenRead(token=token, expires_at=expires_at)


# Antes de /{analysis_id}: si no, "team" se intentaría parsear como id
@router.get("/team", response_model=list[JumpAnalysisRead])
def list_team_analyses(
    coach: User = Depends(require_roles(UserRole.COACH)),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
) -> list[JumpAnalysisRead]:
    return service.list_for_coach(coach)


@router.get("/{analysis_id}", response_model=JumpAnalysisRead)
def get_analysis(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
) -> JumpAnalysisRead:
    return service.get_analysis(current_user, analysis_id)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
) -> None:
    service.delete_analysis(current_user, analysis_id)


@router.get("/{analysis_id}/video-access", response_model=VideoAccessRead)
def get_video_access(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
) -> VideoAccessRead:
    # Mismo control de acceso que GET /{analysis_id}; el token sólo abre este video
    service.get_analysis(current_user, analysis_id)
    token, expires_at = create_video_access_token(analysis_id)
    return VideoAccessRead(token=token, expires_at=expires_at)


@router.get("/{analysis_id}/video", response_class=RedirectResponse, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
def redirect_to_video(
    analysis_id: int,
    token: str = Query(...),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
) -> RedirectResponse:
    # Token en la query (no Bearer): los reproductores de video no mandan headers. El video se
    # sirve desde la URL pública del bucket, que atiende Range: se puede adelantar el video
    verify_video_access_token(token, analysis_id)
    return RedirectResponse(service.get_video_url(analysis_id), status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/by-athlete/{athlete_id}", response_model=list[JumpAnalysisRead])
def list_by_athlete(
    athlete_id: int,
    current_user: User = Depends(get_current_user),
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
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
    service: JumpAnalysisService = Depends(get_jump_analysis_service),
) -> JumpAnalysisRead:
    # Lo llama un proceso interno (pipeline de IA), no una persona: se autentica con
    # la API key de servicio del header X-Service-Api-Key, no con el JWT de usuarios
    return service.ingest_result(analysis_id, result)
