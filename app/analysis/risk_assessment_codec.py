from collections import Counter
from typing import Any, Literal

from kinesiapp.common.v1 import movement_pb2
from pydantic import BaseModel

# Es la forma del JSON de jump_analyses.risk_details que ya guardaba el REST; la IA usa la misma. La vista, el
# lado, el instante del pico y los keyframes son claves opcionales: el JSON de un análisis viejo no cambia
RISK_DETAILS_FORMAT_VERSION = 1

# Uso el mismo nombre de articulación en el JSON de riesgo y en joint_angle_measurements.joint_name
JOINT_NAMES = {
    movement_pb2.JOINT_ANGLE_KNEE_FLEXION: "knee_flexion",
    movement_pb2.JOINT_ANGLE_TRUNK_INCLINATION: "trunk_inclination",
    movement_pb2.JOINT_ANGLE_KNEE_VALGUS: "knee_valgus",
}
SIDE_NAMES = {movement_pb2.BODY_SIDE_LEFT: "left", movement_pb2.BODY_SIDE_RIGHT: "right"}
_DETECTED_BY = {
    movement_pb2.DETECTION_METHOD_LANDING: "landing",
    movement_pb2.DETECTION_METHOD_KNEE_BOTTOM: "knee_bottom",
    movement_pb2.DETECTION_METHOD_TRUNK_HINGE: "trunk_hinge",
    movement_pb2.DETECTION_METHOD_HIP_BOTTOM: "hip_bottom",
}
_DIRECTIONS = {
    movement_pb2.RISK_DIRECTION_HIGHER_IS_RISKIER: "higher_is_riskier",
    movement_pb2.RISK_DIRECTION_LOWER_IS_RISKIER: "lower_is_riskier",
}
_VIEWS = {
    movement_pb2.CAMERA_VIEW_SIDE: "side",
    movement_pb2.CAMERA_VIEW_FRONT: "front",
    movement_pb2.CAMERA_VIEW_INCONCLUSIVE: "inconclusive",
}
_WARNINGS = {movement_pb2.ANALYSIS_WARNING_CAMERA_VIEW_INCONCLUSIVE: "camera_view_inconclusive"}
_LANDMARKS = {
    value: name.removeprefix("BODY_LANDMARK_").lower()
    for name, value in movement_pb2.BodyLandmark.items()
    if value != movement_pb2.BODY_LANDMARK_UNSPECIFIED
}

Side = Literal["left", "right"]


def measurement_name(sample: movement_pb2.JointAngleSample) -> str:
    """Nombre con que guardo una muestra: el valgo va por pierna ("knee_valgus_left") en la misma columna."""
    side = SIDE_NAMES.get(sample.side)
    return f"{JOINT_NAMES[sample.joint]}_{side}" if side else JOINT_NAMES[sample.joint]


def parse_measurement_name(name: str) -> tuple[movement_pb2.JointAngle.ValueType, movement_pb2.BodySide.ValueType]:
    joint_name, _, side_name = name.rpartition("_")
    side = _key_for(SIDE_NAMES, side_name, default=None)
    if side is not None and joint_name in JOINT_NAMES.values():
        return _key_for(JOINT_NAMES, joint_name), side
    return _key_for(JOINT_NAMES, name, default=movement_pb2.JOINT_ANGLE_UNSPECIFIED), movement_pb2.BODY_SIDE_UNSPECIFIED


class _Measured(BaseModel):
    median: float
    min: float
    max: float


class _Signal(BaseModel):
    signal: Literal["knee_flexion", "trunk_inclination", "knee_valgus"]
    direction: Literal["higher_is_riskier", "lower_is_riskier"]
    onset_deg: float
    saturation_deg: float
    measured_deg: _Measured | None
    score_median: float | None
    side: Side | None = None


class _Pattern(BaseModel):
    score: float | None
    repetitions_triggered: int
    signals: dict[str, _Signal]


class _Partial(BaseModel):
    measured_deg: float | None
    score: float | None
    side: Side | None = None
    peak_ms: int | None = None


class _Keyframe(BaseModel):
    timestamp_ms: int
    # Coordenadas normalizadas [x, y] por punto del cuerpo
    keypoints: dict[str, tuple[float, float]]


class _Repetition(BaseModel):
    start_ms: int
    end_ms: int
    detected_by: Literal["landing", "knee_bottom", "trunk_hinge", "hip_bottom"]
    pattern_scores: dict[str, float | None]
    partials: dict[str, _Partial]
    keyframes: list[_Keyframe] = []


class _RiskDetails(BaseModel):
    format_version: Literal[1]
    risk_score: float
    dominant_pattern: str | None
    patterns: dict[str, _Pattern]
    repetitions: list[_Repetition]
    # Ausente en los análisis anteriores a la detección de vista
    camera_view: Literal["side", "front", "inconclusive"] | None = None
    warnings: list[Literal["camera_view_inconclusive"]] = []


class RiskAssessmentCodec:
    """Adapter entre el RiskAssessment del contrato y el JSON risk_details que guardo en la base.

    Guardo el mismo JSON que el REST para que los análisis viejos y los nuevos se lean igual. El nivel
    no va en el JSON: lo recibo aparte porque sale de los cortes configurados.
    """

    def to_details(self, assessment: movement_pb2.RiskAssessment) -> dict[str, Any]:
        details = {
            "format_version": RISK_DETAILS_FORMAT_VERSION,
            "risk_score": assessment.risk_score,
            "dominant_pattern": _optional(assessment, "dominant_pattern"),
            "repetitions_evaluated": len(assessment.repetitions),
            "detection_methods": dict(Counter(_DETECTED_BY[rep.detected_by] for rep in assessment.repetitions)),
            "patterns": {pattern.code: _pattern_details(pattern) for pattern in assessment.patterns},
            "repetitions": [_repetition_details(rep) for rep in assessment.repetitions],
        }
        if assessment.camera_view in _VIEWS:
            details["camera_view"] = _VIEWS[assessment.camera_view]
        if assessment.warnings:
            details["warnings"] = [_WARNINGS[warning] for warning in assessment.warnings]
        return details

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
            camera_view=_key_for(_VIEWS, parsed.camera_view, default=movement_pb2.CAMERA_VIEW_UNSPECIFIED),
            warnings=[_key_for(_WARNINGS, warning) for warning in parsed.warnings],
        )


def _pattern_details(pattern: movement_pb2.RiskPattern) -> dict[str, Any]:
    return {
        "score": _optional(pattern, "score"),
        "repetitions_triggered": pattern.repetitions_triggered,
        "signals": {signal.code: _signal_details(signal) for signal in pattern.signals},
    }


def _signal_details(signal: movement_pb2.RiskSignal) -> dict[str, Any]:
    details = {
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
    if signal.side in SIDE_NAMES:
        details["side"] = SIDE_NAMES[signal.side]
    return details


def _repetition_details(rep: movement_pb2.Repetition) -> dict[str, Any]:
    details = {
        "start_ms": rep.start_ms,
        "end_ms": rep.end_ms,
        "detected_by": _DETECTED_BY[rep.detected_by],
        "pattern_scores": {score.code: _optional(score, "score") for score in rep.pattern_scores},
        "partials": {score.code: _partial_details(score) for score in rep.signal_scores},
    }
    if rep.keyframes:
        details["keyframes"] = [
            {
                "timestamp_ms": frame.timestamp_ms,
                "keypoints": {_LANDMARKS[point.landmark]: [point.x, point.y] for point in frame.keypoints},
            }
            for frame in rep.keyframes
        ]
    return details


def _partial_details(score: movement_pb2.RepetitionScore) -> dict[str, Any]:
    details = {"measured_deg": _optional(score, "measured_degrees"), "score": _optional(score, "score")}
    if score.side in SIDE_NAMES:
        details["side"] = SIDE_NAMES[score.side]
    if score.HasField("peak_ms"):
        details["peak_ms"] = score.peak_ms
    return details


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
        side=_side(signal.side),
    )


def _repetition(rep: _Repetition) -> movement_pb2.Repetition:
    return movement_pb2.Repetition(
        start_ms=rep.start_ms,
        end_ms=rep.end_ms,
        detected_by=_key_for(_DETECTED_BY, rep.detected_by),
        pattern_scores=[movement_pb2.RepetitionScore(code=code, score=score) for code, score in rep.pattern_scores.items()],
        signal_scores=[
            movement_pb2.RepetitionScore(
                code=code,
                score=partial.score,
                measured_degrees=partial.measured_deg,
                side=_side(partial.side),
                peak_ms=partial.peak_ms,
            )
            for code, partial in rep.partials.items()
        ],
        keyframes=[
            movement_pb2.PoseKeyframe(
                timestamp_ms=frame.timestamp_ms,
                keypoints=[
                    movement_pb2.Keypoint(landmark=_key_for(_LANDMARKS, name), x=x, y=y)
                    for name, (x, y) in frame.keypoints.items()
                    if name in _LANDMARKS.values()
                ],
            )
            for frame in rep.keyframes
        ],
    )


def _side(side: Side | None) -> movement_pb2.BodySide.ValueType:
    return _key_for(SIDE_NAMES, side, default=movement_pb2.BODY_SIDE_UNSPECIFIED)


_MISSING = object()


def _key_for(mapping: dict[int, str], value: str | None, default: Any = _MISSING) -> Any:
    key = next((key for key, name in mapping.items() if name == value), default)
    if key is _MISSING:
        raise KeyError(value)
    return key


def _optional(message: Any, field: str) -> Any:
    return getattr(message, field) if message.HasField(field) else None
