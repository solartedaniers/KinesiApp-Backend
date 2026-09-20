from app.core.exceptions import NotFoundException
from app.models.jump_analysis import JointAngleMeasurement, JumpAnalysis, JumpAnalysisStatus
from app.repositories.athlete_repository import AthleteRepository
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JumpAnalysisCreate, JumpAnalysisResultIngest


class JumpAnalysisService:
    """Orquesta el ciclo de vida de un salto: creación, y luego ingesta del resultado de la IA."""

    def __init__(self, repository: JumpAnalysisRepository, athlete_repository: AthleteRepository) -> None:
        self._repository = repository
        self._athlete_repository = athlete_repository

    def create_analysis(self, data: JumpAnalysisCreate) -> JumpAnalysis:
        if self._athlete_repository.get(data.athlete_id) is None:
            raise NotFoundException("AthleteProfile", data.athlete_id)

        analysis = JumpAnalysis(athlete_id=data.athlete_id, video_reference=data.video_reference)
        return self._repository.add(analysis)

    def get_analysis(self, analysis_id: int) -> JumpAnalysis:
        analysis = self._repository.get(analysis_id)
        if analysis is None:
            raise NotFoundException("JumpAnalysis", analysis_id)
        return analysis

    def list_by_athlete(self, athlete_id: int) -> list[JumpAnalysis]:
        return self._repository.list_by_athlete(athlete_id)

    def ingest_result(self, analysis_id: int, result: JumpAnalysisResultIngest) -> JumpAnalysis:
        # Punto de entrada donde el pipeline de IA reporta ángulos articulares y score de riesgo
        analysis = self.get_analysis(analysis_id)
        analysis.risk_score = result.risk_score
        analysis.status = JumpAnalysisStatus.PROCESSED
        analysis.angle_measurements = [
            JointAngleMeasurement(**measurement.model_dump()) for measurement in result.measurements
        ]
        return self._repository.add(analysis)
