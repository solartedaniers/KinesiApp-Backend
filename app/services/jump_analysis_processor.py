import logging
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.models.jump_analysis import JumpAnalysisStatus
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JointAngleMeasurementCreate, JumpAnalysisResultIngest
from app.services.jump_analysis_service import JumpAnalysisService

logger = logging.getLogger(__name__)


class JumpVideoAnalyzer:
    """Cómputo pesado del salto: frames del video → ángulos articulares → score de riesgo.

    Es síncrono y lento a propósito: nunca se llama desde el request, sólo desde
    JumpAnalysisProcessor en segundo plano.
    """

    def __init__(self, safe_knee_flexion_deg: float) -> None:
        self._safe_knee_flexion_deg = safe_knee_flexion_deg

    def analyze(self, video_path: Path) -> JumpAnalysisResultIngest:
        measurements = self._extract_knee_flexion(video_path)
        return JumpAnalysisResultIngest(
            risk_score=self._risk_score(measurements), measurements=measurements
        )

    def _extract_knee_flexion(self, video_path: Path) -> list[JointAngleMeasurementCreate]:
        if not video_path.is_file():
            raise FileNotFoundError(video_path)
        # ponytail: serie de demostración, no hay modelo de pose instalado todavía. Reemplazar
        # por MediaPipe frame a frame (docs/design/video-analysis-pipeline.md §5)
        demo_series = [(0, 12.0), (200, 35.0), (400, 48.0), (600, 41.0)]
        return [
            JointAngleMeasurementCreate(
                joint_name="knee_flexion", angle_degrees=angle, frame_timestamp_ms=timestamp
            )
            for timestamp, angle in demo_series
        ]

    def _risk_score(self, measurements: list[JointAngleMeasurementCreate]) -> float:
        # Aterrizaje rígido (poca flexión de rodilla) = más riesgo; 0 cuando llega a la flexión segura
        peak_flexion = max((m.angle_degrees for m in measurements), default=0.0)
        return round(max(0.0, 1 - peak_flexion / self._safe_knee_flexion_deg), 3)


class JumpAnalysisProcessor:
    """Procesa un análisis PENDING después de responder al cliente (BackgroundTasks).

    Abre su propia sesión de base de datos: la del request ya está cerrada cuando corre.
    ponytail: corre en el threadpool del mismo proceso de la API; si se reinicia el servidor el
    análisis queda PENDING. Pasar a Celery/Redis (ver docs/design) cuando haya carga real.
    """

    def __init__(self, session_factory: sessionmaker[Session], analyzer: JumpVideoAnalyzer) -> None:
        self._session_factory = session_factory
        self._analyzer = analyzer

    def process(self, analysis_id: int) -> None:
        with self._session_factory() as db:
            repository = JumpAnalysisRepository(db)
            analysis = repository.get(analysis_id)
            if analysis is None or analysis.status != JumpAnalysisStatus.PENDING:
                return
            try:
                result = self._analyzer.analyze(Path(analysis.video_reference))
            except Exception:
                logger.exception("Jump analysis %s failed", analysis_id)
                analysis.status = JumpAnalysisStatus.FAILED
            else:
                JumpAnalysisService.apply_result(analysis, result)
            repository.add(analysis)
