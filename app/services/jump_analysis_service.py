from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.athlete import AthleteProfile
from app.models.jump_analysis import JointAngleMeasurement, JumpAnalysis, JumpAnalysisStatus
from app.models.user import User, UserRole
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JumpAnalysisCreate, JumpAnalysisResultIngest


class JumpAnalysisService:
    """Orquesta el ciclo de vida de un salto: creación, y luego ingesta del resultado de la IA.

    La ingesta de resultados (ingest_result) la invoca el pipeline de IA, no un usuario de
    KinesiApp con rol propio, así que queda fuera del chequeo de roles de este servicio.
    """

    def __init__(self, repository: JumpAnalysisRepository, athlete_repository: AthleteRepository) -> None:
        self._repository = repository
        self._athlete_repository = athlete_repository

    def create_analysis(self, current_user: User, data: JumpAnalysisCreate) -> JumpAnalysis:
        athlete = self._get_athlete_or_404(data.athlete_id)
        # Sólo el propio deportista sube sus saltos; un admin puede hacerlo en su nombre
        self._authorize_athlete_access(current_user, athlete, allow_coach=False)

        analysis = JumpAnalysis(athlete_id=data.athlete_id, video_reference=data.video_reference)
        return self._repository.add(analysis)

    def get_analysis(self, current_user: User, analysis_id: int) -> JumpAnalysis:
        analysis = self._repository.get(analysis_id)
        if analysis is None:
            raise NotFoundException("JumpAnalysis", analysis_id)
        athlete = self._get_athlete_or_404(analysis.athlete_id)
        self._authorize_athlete_access(current_user, athlete, allow_coach=True)
        return analysis

    def list_by_athlete(self, current_user: User, athlete_id: int) -> list[JumpAnalysis]:
        athlete = self._get_athlete_or_404(athlete_id)
        self._authorize_athlete_access(current_user, athlete, allow_coach=True)
        return self._repository.list_by_athlete(athlete_id)

    def ingest_result(self, analysis_id: int, result: JumpAnalysisResultIngest) -> JumpAnalysis:
        # Punto de entrada donde el pipeline de IA reporta ángulos articulares y score de riesgo.
        # Este cómputo pesado corre en el pipeline externo, no en el hilo de este endpoint:
        # el request sólo persiste el resultado ya calculado (patrón webhook, no bloquea el event loop)
        analysis = self._repository.get(analysis_id)
        if analysis is None:
            raise NotFoundException("JumpAnalysis", analysis_id)
        analysis.risk_score = result.risk_score
        analysis.status = JumpAnalysisStatus.PROCESSED
        analysis.angle_measurements = [
            JointAngleMeasurement(**measurement.model_dump()) for measurement in result.measurements
        ]
        return self._repository.add(analysis)

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
