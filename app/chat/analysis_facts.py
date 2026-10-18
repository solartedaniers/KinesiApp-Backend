from kinesiapp.ai.v1 import assistant_pb2
from kinesiapp.common.v1 import movement_pb2

from app.analysis.risk_assessment_codec import RiskAssessmentCodec
from app.analysis.risk_level import RiskLevelClassifier
from app.models.jump_analysis import JumpAnalysis, MovementType

_MOVEMENT_TYPES = {
    MovementType.JUMP: movement_pb2.MOVEMENT_TYPE_JUMP,
    MovementType.SQUAT: movement_pb2.MOVEMENT_TYPE_SQUAT,
}


class AnalysisFactsBuilder:
    """Armo los datos del análisis que le mando al asistente: nada del video ni de la persona."""

    def __init__(self, codec: RiskAssessmentCodec, levels: RiskLevelClassifier) -> None:
        self._codec = codec
        self._levels = levels

    def build(self, analysis: JumpAnalysis) -> assistant_pb2.AnalysisFacts:
        facts = assistant_pb2.AnalysisFacts(
            movement_type=_MOVEMENT_TYPES[analysis.movement_type],
            risk_score=analysis.risk_score or 0.0,
            dominant_risk_pattern=analysis.dominant_risk_pattern,
        )
        # Los análisis anteriores al desglose no lo tienen: la IA responde en modo reducido
        if analysis.risk_details is not None:
            facts.risk_assessment.CopyFrom(
                self._codec.to_assessment(analysis.risk_details, self._levels.level(analysis.risk_score))
            )
        return facts
