import logging

from kinesiapp.analysis.v1 import analysis_pb2
from kinesiapp.common.v1 import movement_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from pydantic import ValidationError

from app.analysis.progress import AnalysisProgressUpdate
from app.analysis.knee_reading import KneeReadingExtractor
from app.analysis.risk_assessment_codec import JOINT_NAMES, RiskAssessmentCodec
from app.analysis.risk_level import RiskLevelClassifier
from app.models.jump_analysis import JointAngleMeasurement, JumpAnalysis, JumpAnalysisStatus
from app.rpc.proto_values import timestamp

logger = logging.getLogger(__name__)

_JOINTS = {name: joint for joint, name in JOINT_NAMES.items()}


class AnalysisMessages:
    """Paso los análisis del modelo a los mensajes del contrato; el nivel de riesgo lo calculo aquí."""

    def __init__(self, codec: RiskAssessmentCodec, levels: RiskLevelClassifier, knee: KneeReadingExtractor) -> None:
        self._codec = codec
        self._levels = levels
        self._knee = knee

    def summary(self, analysis: JumpAnalysis) -> analysis_pb2.AnalysisSummary:
        return self._summary(analysis, self._assessment(analysis))

    def _summary(
        self, analysis: JumpAnalysis, assessment: movement_pb2.RiskAssessment | None
    ) -> analysis_pb2.AnalysisSummary:
        message = analysis_pb2.AnalysisSummary(
            id=analysis.id,
            athlete_id=analysis.athlete_id,
            movement_type=movement_pb2.MovementType.Value(f"MOVEMENT_TYPE_{analysis.movement_type.name}"),
            status=movement_pb2.AnalysisStatus.Value(f"ANALYSIS_STATUS_{analysis.status.name}"),
            recorded_at=timestamp(analysis.recorded_at),
        )
        if analysis.status is JumpAnalysisStatus.PROCESSED and analysis.risk_score is not None:
            message.risk_score = analysis.risk_score
            message.risk_level = self._levels.level(analysis.risk_score)
            if analysis.dominant_risk_pattern is not None:
                message.dominant_risk_pattern = analysis.dominant_risk_pattern
        if assessment is not None:
            knee = self._knee.read(assessment)
            if knee.median_peak_degrees is not None:
                message.knee_median_peak_degrees = knee.median_peak_degrees
            if knee.target is not None:
                message.knee_target.CopyFrom(knee.target)
        if analysis.status is JumpAnalysisStatus.FAILED:
            message.failure_reason = _failure_reason(analysis.failure_reason)
        return message

    def detail(self, analysis: JumpAnalysis) -> analysis_pb2.Analysis:
        samples = sorted(analysis.angle_measurements, key=lambda sample: (sample.frame_timestamp_ms, sample.id))
        assessment = self._assessment(analysis)
        message = analysis_pb2.Analysis(
            summary=self._summary(analysis, assessment),
            angle_samples=[_sample(sample) for sample in samples],
            pose_model_version=analysis.pose_model_version,
            risk_model_version=analysis.risk_model_version,
        )
        if assessment is not None:
            message.risk_assessment.CopyFrom(assessment)
        return message

    def _assessment(self, analysis: JumpAnalysis) -> movement_pb2.RiskAssessment | None:
        if analysis.status is not JumpAnalysisStatus.PROCESSED or analysis.risk_details is None:
            return None
        try:
            return self._codec.to_assessment(analysis.risk_details, self._levels.level(analysis.risk_score))
        except ValidationError:
            # No dejo que un JSON viejo que no cuadra tumbe la consulta: muestro el resto sin el desglose
            logger.warning("Analysis %s has unreadable risk details", analysis.id)
            return None


def progress(update: AnalysisProgressUpdate) -> movement_pb2.AnalysisProgress:
    return movement_pb2.AnalysisProgress(
        stage=movement_pb2.AnalysisStage.Value(f"ANALYSIS_STAGE_{update.stage.name}"),
        frames_processed=update.frames_processed,
        frames_total=update.frames_total,
    )


def _failure_reason(reason: str | None) -> ErrorReason.ValueType:
    name = f"ERROR_REASON_{reason}"
    return ErrorReason.Value(name) if name in ErrorReason.keys() else ErrorReason.ERROR_REASON_UNSPECIFIED


def _sample(sample: JointAngleMeasurement) -> movement_pb2.JointAngleSample:
    return movement_pb2.JointAngleSample(
        joint=_JOINTS.get(sample.joint_name, movement_pb2.JOINT_ANGLE_UNSPECIFIED),
        angle_degrees=sample.angle_degrees,
        frame_timestamp_ms=sample.frame_timestamp_ms,
    )
