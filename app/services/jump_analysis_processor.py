import logging
import math
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.analysis.angles import AngleCalculator, AngleSeries
from app.analysis.errors import NoMovementDetectedError, VideoAnalysisError
from app.analysis.movement_windows import MovementWindowDetector
from app.analysis.pose_extraction import VideoPoseExtractor
from app.analysis.pose_series import PoseSeries
from app.analysis.preprocessing import LandmarkSeriesPreprocessor
from app.analysis.risk import RiskScoreAggregator
from app.models.jump_analysis import JumpAnalysisStatus, MovementType
from app.repositories.jump_analysis_repository import JumpAnalysisRepository
from app.schemas.jump_analysis import JointAngleMeasurementCreate, JumpAnalysisResultIngest
from app.services.jump_analysis_service import JumpAnalysisService

logger = logging.getLogger(__name__)

KNEE_FLEXION_JOINT = "knee_flexion"
TRUNK_INCLINATION_JOINT = "trunk_inclination"


@dataclass(frozen=True)
class MovementRiskProfile:
    """Cómo se evalúa un tipo de movimiento: dónde mirar y cómo puntuar."""

    window_detector: MovementWindowDetector
    aggregator: RiskScoreAggregator


class JumpVideoAnalyzer:
    """Video → pose → ángulos → ventanas del movimiento → riesgo por patrones.

    Síncrono y lento a propósito: nunca se llama desde el request, sólo desde
    JumpAnalysisProcessor en segundo plano.
    """

    def __init__(
        self,
        pose_extractor: VideoPoseExtractor,
        preprocessor: LandmarkSeriesPreprocessor,
        angle_calculator: AngleCalculator,
        profiles: dict[MovementType, MovementRiskProfile],
        pose_model_version: str,
        risk_model_version: str,
    ) -> None:
        self._pose_extractor = pose_extractor
        self._preprocessor = preprocessor
        self._angle_calculator = angle_calculator
        self._profiles = profiles
        self._pose_model_version = pose_model_version
        self._risk_model_version = risk_model_version

    def analyze(self, video_path: Path, movement_type: MovementType) -> JumpAnalysisResultIngest:
        series = self._preprocessor.process(self._pose_extractor.extract(video_path))
        angles = self._angle_calculator.calculate(series)
        profile = self._profiles[movement_type]
        windows = profile.window_detector.detect(series, angles)
        if not windows:
            raise NoMovementDetectedError(f"No {movement_type.value} found in {video_path}")
        risk = profile.aggregator.aggregate(angles, windows)
        return JumpAnalysisResultIngest(
            risk_score=round(risk.risk_score, 3),
            dominant_risk_pattern=risk.dominant_pattern,
            pose_model_version=self._pose_model_version,
            risk_model_version=self._risk_model_version,
            measurements=self._measurements(series, angles),
        )

    @staticmethod
    def _measurements(series: PoseSeries, angles: AngleSeries) -> list[JointAngleMeasurementCreate]:
        return [
            JointAngleMeasurementCreate(
                joint_name=joint, angle_degrees=round(float(angle), 1), frame_timestamp_ms=series.frame_timestamp_ms(frame)
            )
            for joint, values in ((KNEE_FLEXION_JOINT, angles.knee_flexion), (TRUNK_INCLINATION_JOINT, angles.trunk_inclination))
            for frame, angle in enumerate(values)
            if not math.isnan(angle)
        ]


class JumpAnalysisProcessor:
    """Procesa un análisis PENDING después de responder al cliente (BackgroundTasks).

    Abre su propia sesión de base de datos: la del request ya está cerrada cuando corre.
    ponytail: corre en el threadpool del mismo proceso de la API; si se reinicia el servidor el
    análisis queda PENDING. Pasar a una cola (ver docs/design) cuando haya carga real.
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
                result = self._analyzer.analyze(Path(analysis.video_reference), analysis.movement_type)
            except VideoAnalysisError as error:
                logger.warning("Jump analysis %s failed: %s", analysis_id, error)
                analysis.status = JumpAnalysisStatus.FAILED
            except Exception:
                logger.exception("Jump analysis %s failed", analysis_id)
                analysis.status = JumpAnalysisStatus.FAILED
            else:
                JumpAnalysisService.apply_result(analysis, result)
            repository.add(analysis)
