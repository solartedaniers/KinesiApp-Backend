from pathlib import Path
from typing import BinaryIO

from app.core.exceptions import ErrorCode, ForbiddenException, NotFoundException
from app.models.athlete import AthleteProfile
from app.models.jump_analysis import JointAngleMeasurement, JumpAnalysis, JumpAnalysisStatus, MovementType
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JumpAnalysisResultIngest
from app.services.jump_video_storage import JumpVideoStorage


class JumpAnalysisService:
    """Orquesta el ciclo de vida de un salto: creación, y luego ingesta del resultado de la IA.

    La ingesta de resultados (ingest_result) la invoca el pipeline de IA, no un usuario de
    KinesiApp con rol propio, así que queda fuera del chequeo de roles de este servicio.
    """

    def __init__(
        self,
        repository: JumpAnalysisRepository,
        athlete_repository: AthleteRepository,
        video_storage: JumpVideoStorage,
        required_consent_version: int,
    ) -> None:
        self._repository = repository
        self._athlete_repository = athlete_repository
        self._video_storage = video_storage
        self._required_consent_version = required_consent_version

    def create_from_upload(
        self,
        current_user: User,
        athlete_id: int,
        movement_type: MovementType,
        video: BinaryIO,
        content_type: str | None,
    ) -> JumpAnalysis:
        # Se autoriza antes de escribir en disco: un intruso no llega a ocupar espacio
        self._authorize_upload(current_user, athlete_id)
        self._require_video_consent(current_user)
        video_path = self._video_storage.save(video, content_type)
        try:
            return self._repository.add(
                JumpAnalysis(
                    athlete_id=athlete_id, movement_type=movement_type, video_reference=str(video_path)
                )
            )
        except Exception:
            self._video_storage.delete(video_path)
            raise

    def get_analysis(self, current_user: User, analysis_id: int) -> JumpAnalysis:
        analysis = self._repository.get(analysis_id)
        if analysis is None:
            raise NotFoundException("JumpAnalysis", analysis_id)
        athlete = self._get_athlete_or_404(analysis.athlete_id)
        self._authorize_athlete_access(current_user, athlete, allow_coach=True)
        return analysis

    def delete_analysis(self, current_user: User, analysis_id: int) -> None:
        # Mismo criterio de acceso que la lectura (get_analysis): dueño, coach asignado o admin
        analysis = self.get_analysis(current_user, analysis_id)
        video_path = Path(analysis.video_reference)
        # Primero la fila (arrastra sus mediciones por cascade del ORM) y después el
        # archivo: si el commit falla, el video sigue en disco y nada queda a medias
        self._repository.delete(analysis)
        self._video_storage.delete(video_path)

    def get_video_path(self, analysis_id: int) -> Path:
        # Sin chequeo de rol: quien llega aquí ya presentó un token de video emitido
        # tras pasar get_analysis (ver la ruta /{analysis_id}/video)
        analysis = self._repository.get(analysis_id)
        if analysis is None:
            raise NotFoundException("JumpAnalysis", analysis_id)
        path = Path(analysis.video_reference)
        if not path.is_file():
            raise NotFoundException("JumpVideo", analysis_id, code=ErrorCode.VIDEO_NOT_FOUND)
        return path

    def list_by_athlete(self, current_user: User, athlete_id: int) -> list[JumpAnalysis]:
        athlete = self._get_athlete_or_404(athlete_id)
        self._authorize_athlete_access(current_user, athlete, allow_coach=True)
        return self._repository.list_by_athlete(athlete_id)

    def list_for_coach(self, coach: User) -> list[JumpAnalysis]:
        # Vista de equipo: los saltos de todos los deportistas a cargo del coach
        return self._repository.list_by_coach(coach.id)

    def ingest_result(self, analysis_id: int, result: JumpAnalysisResultIngest) -> JumpAnalysis:
        # Punto de entrada donde el pipeline de IA reporta ángulos articulares y score de riesgo.
        # Este cómputo pesado corre en el pipeline externo, no en el hilo de este endpoint:
        # el request sólo persiste el resultado ya calculado (patrón webhook, no bloquea el event loop)
        analysis = self._repository.get(analysis_id)
        if analysis is None:
            raise NotFoundException("JumpAnalysis", analysis_id)
        self.apply_result(analysis, result)
        return self._repository.add(analysis)

    @staticmethod
    def apply_result(analysis: JumpAnalysis, result: JumpAnalysisResultIngest) -> None:
        # Compartido por el webhook y por el procesamiento en segundo plano
        analysis.risk_score = result.risk_score
        analysis.dominant_risk_pattern = result.dominant_risk_pattern
        analysis.risk_details = result.risk_details
        analysis.pose_model_version = result.pose_model_version
        analysis.risk_model_version = result.risk_model_version
        analysis.status = JumpAnalysisStatus.PROCESSED
        analysis.angle_measurements = [
            JointAngleMeasurement(**measurement.model_dump()) for measurement in result.measurements
        ]

    def _authorize_upload(self, current_user: User, athlete_id: int) -> None:
        athlete = self._get_athlete_or_404(athlete_id)
        # El propio deportista sube sus saltos; los gestionados (sin cuenta) los sube su coach
        self._authorize_athlete_access(current_user, athlete, allow_coach=athlete.is_managed)

    def _require_video_consent(self, uploader: User) -> None:
        # Quien graba/sube debe haber aceptado la versión vigente del texto: el propio
        # deportista, o el coach en el caso de un deportista gestionado (sin cuenta)
        if uploader.video_consent_version != self._required_consent_version:
            raise ForbiddenException("Video consent is required", code=ErrorCode.CONSENT_REQUIRED)

    def _get_athlete_or_404(self, athlete_id: int) -> AthleteProfile:
        athlete = self._athlete_repository.get(athlete_id)
        if athlete is None:
            raise NotFoundException("AthleteProfile", athlete_id)
        return athlete

    def _authorize_athlete_access(
        self, current_user: User, athlete: AthleteProfile, *, allow_coach: bool
    ) -> None:
        # Regla de negocio de quién puede ver/tocar los saltos de un deportista:
        # el propio deportista, su coach asignado (sólo lectura) o un admin
        if current_user.role == UserRole.ADMIN:
            return
        if current_user.role == UserRole.ATHLETE and athlete.user_id == current_user.id:
            return
        if allow_coach and current_user.role == UserRole.COACH and athlete.coach_id == current_user.id:
            return
        raise ForbiddenException("You don't have access to this athlete's analyses")
