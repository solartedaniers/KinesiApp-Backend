from collections import Counter
from typing import Any, Literal

from kinesiapp.common.v1 import movement_pb2
from pydantic import BaseModel

# Es la forma del JSON de jump_analyses.risk_details que ya guardaba el REST; la IA usa la misma
RISK_DETAILS_FORMAT_VERSION = 1

# Nombre de cada articulación en el JSON de riesgo y en joint_angle_measurements.joint_name
JOINT_NAMES = {
    movement_pb2.JOINT_ANGLE_KNEE_FLEXION: "knee_flexion",
    movement_pb2.JOINT_ANGLE_TRUNK_INCLINATION: "trunk_inclination",
}
_DETECTED_BY = {
    movement_pb2.DETECTION_METHOD_LANDING: "landing",
    movement_pb2.DETECTION_METHOD_KNEE_BOTTOM: "knee_bottom",
    movement_pb2.DETECTION_METHOD_TRUNK_HINGE: "trunk_hinge",
}
_DIRECTIONS = {
    movement_pb2.RISK_DIRECTION_HIGHER_IS_RISKIER: "higher_is_riskier",
    movement_pb2.RISK_DIRECTION_LOWER_IS_RISKIER: "lower_is_riskier",
}


class _Measured(BaseModel):
    median: float
    min: float
    max: float


class _Signal(BaseModel):
    signal: Literal["knee_flexion", "trunk_inclination"]
    direction: Literal["higher_is_riskier", "lower_is_riskier"]
    onset_deg: float
    saturation_deg: float
    measured_deg: _Measured | None
    score_median: float | None


class _Pattern(BaseModel):
    score: float | None
    repetitions_triggered: int
    signals: dict[str, _Signal]


class _Partial(BaseModel):
    measured_deg: float | None
    score: float | None


class _Repetition(BaseModel):
    start_ms: int
    end_ms: int
    detected_by: Literal["landing", "knee_bottom", "trunk_hinge"]
    pattern_scores: dict[str, float | None]
    partials: dict[str, _Partial]


class _RiskDetails(BaseModel):
    format_version: Literal[1]
    risk_score: float
    dominant_pattern: str | None
    patterns: dict[str, _Pattern]
    repetitions: list[_Repetition]


class RiskAssessmentCodec:
    """Adapter entre el RiskAssessment del contrato y el JSON risk_details que guardo en la base.

    Guardo el mismo JSON que el REST para que los análisis viejos y los nuevos se lean igual. El nivel
    no va en el JSON: lo recibo aparte porque sale de los cortes configurados.
    """

    def to_details(self, assessment: movement_pb2.RiskAssessment) -> dict[str, Any]:
        return {
            "format_version": RISK_DETAILS_FORMAT_VERSION,
            "risk_score": assessment.risk_score,
            "dominant_pattern": _optional(assessment, "dominant_pattern"),
            "repetitions_evaluated": len(assessment.repetitions),
            "detection_methods": dict(Counter(_DETECTED_BY[rep.detected_by] for rep in assessment.repetitions)),
            "patterns": {pattern.code: _pattern_details(pattern) for pattern in assessment.patterns},
            "repetitions": [_repetition_details(rep) for rep in assessment.repetitions],
        }

    def to_assessment(
        self, details: dict[str, Any], risk_level: movement_pb2.RiskLevel.ValueType
    ) -> movement_pb2.RiskAssessment:
        # Valido el JSON al leerlo: lo escribieron versiones anteriores del backend
        parsed = _RiskDetails.model_validate(details)
        return movement_pb2.RiskAssessment(
            risk_score=parsed.risk_score,
            risk_level=risk_level,
            dominant_pattern=parsed.dominant_pattern,
            patterns=[_pattern(code, pattern) for code, pattern in parsed.patterns.items()],
            repetitions=[_repetition(rep) for rep in parsed.repetitions],
        )


def _pattern_details(pattern: movement_pb2.RiskPattern) -> dict[str, Any]:
    return {
        "score": _optional(pattern, "score"),
        "repetitions_triggered": pattern.repetitions_triggered,
        "signals": {
            signal.code: {
                "signal": JOINT_NAMES[signal.joint],
                "direction": _DIRECTIONS[signal.direction],
                "onset_deg": signal.onset_degrees,
                "saturation_deg": signal.saturation_degrees,
                "measured_deg": (
                    {
                        "median": signal.measured.median_degrees,
                        "min": signal.measured.min_degrees,
                        "max": signal.measured.max_degrees,
                    }
                    if signal.HasField("measured")
                    else None
                ),
                "score_median": _optional(signal, "score_median"),
            }
            for signal in pattern.signals
        },
    }


def _repetition_details(rep: movement_pb2.Repetition) -> dict[str, Any]:
    return {
        "start_ms": rep.start_ms,
        "end_ms": rep.end_ms,
        "detected_by": _DETECTED_BY[rep.detected_by],
        "pattern_scores": {score.code: _optional(score, "score") for score in rep.pattern_scores},
        "partials": {
            score.code: {"measured_deg": _optional(score, "measured_degrees"), "score": _optional(score, "score")}
            for score in rep.signal_scores
        },
    }


def _pattern(code: str, pattern: _Pattern) -> movement_pb2.RiskPattern:
    return movement_pb2.RiskPattern(
        code=code,
        score=pattern.score,
        repetitions_triggered=pattern.repetitions_triggered,
        signals=[_signal(signal_code, signal) for signal_code, signal in pattern.signals.items()],
    )


def _signal(code: str, signal: _Signal) -> movement_pb2.RiskSignal:
    measured = signal.measured_deg
    return movement_pb2.RiskSignal(
        code=code,
        joint=_key_for(JOINT_NAMES, signal.signal),
        direction=_key_for(_DIRECTIONS, signal.direction),
        onset_degrees=signal.onset_deg,
        saturation_degrees=signal.saturation_deg,
        measured=(
            movement_pb2.AngleSummary(median_degrees=measured.median, min_degrees=measured.min, max_degrees=measured.max)
            if measured
            else None
        ),
        score_median=signal.score_median,
    )


def _repetition(rep: _Repetition) -> movement_pb2.Repetition:
    return movement_pb2.Repetition(
        start_ms=rep.start_ms,
        end_ms=rep.end_ms,
        detected_by=_key_for(_DETECTED_BY, rep.detected_by),
        pattern_scores=[movement_pb2.RepetitionScore(code=code, score=score) for code, score in rep.pattern_scores.items()],
        signal_scores=[
            movement_pb2.RepetitionScore(code=code, score=partial.score, measured_degrees=partial.measured_deg)
            for code, partial in rep.partials.items()
        ],
    )


def _key_for(mapping: dict[int, str], value: str) -> int:
    return next(key for key, name in mapping.items() if name == value)


def _optional(message: Any, field: str) -> Any:
    return getattr(message, field) if message.HasField(field) else None
