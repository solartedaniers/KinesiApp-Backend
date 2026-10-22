"""Pruebo que la lectura de la rodilla salga solo de las señales que guardó la IA."""

import json
from pathlib import Path

from kinesiapp.common.v1 import movement_pb2

from app.analysis.knee_reading import KneeReadingExtractor
from app.analysis.risk_assessment_codec import RiskAssessmentCodec

SAMPLE = json.loads((Path(__file__).parent / "risk_details_sample.json").read_text(encoding="utf-8"))

LOWER = movement_pb2.RISK_DIRECTION_LOWER_IS_RISKIER
HIGHER = movement_pb2.RISK_DIRECTION_HIGHER_IS_RISKIER
KNEE = movement_pb2.JOINT_ANGLE_KNEE_FLEXION
TRUNK = movement_pb2.JOINT_ANGLE_TRUNK_INCLINATION


def _assessment(*signals: movement_pb2.RiskSignal) -> movement_pb2.RiskAssessment:
    return movement_pb2.RiskAssessment(patterns=[movement_pb2.RiskPattern(code="p", signals=list(signals))])


def test_the_jump_gets_both_limits_and_the_median_of_the_peaks() -> None:
    reading = KneeReadingExtractor().read(RiskAssessmentCodec().to_assessment(SAMPLE, movement_pb2.RISK_LEVEL_HIGH))

    assert reading.median_peak_degrees == 109.5
    assert (reading.target.low_degrees, reading.target.high_degrees) == (60.0, 80.0)


def test_the_squat_has_only_a_lower_limit() -> None:
    reading = KneeReadingExtractor().read(_assessment(
        movement_pb2.RiskSignal(code="squat_knee_shallow", joint=KNEE, direction=LOWER, onset_degrees=90, saturation_degrees=80),
        movement_pb2.RiskSignal(code="squat_trunk_lean", joint=TRUNK, direction=HIGHER, onset_degrees=70, saturation_degrees=90),
    ))

    assert reading.target.low_degrees == 90 and not reading.target.HasField("high_degrees")
    assert reading.median_peak_degrees is None


def test_without_knee_signals_there_is_no_target() -> None:
    reading = KneeReadingExtractor().read(_assessment(
        movement_pb2.RiskSignal(code="trunk_lean", joint=TRUNK, direction=HIGHER, onset_degrees=25, saturation_degrees=45),
    ))

    assert (reading.median_peak_degrees, reading.target) == (None, None)
