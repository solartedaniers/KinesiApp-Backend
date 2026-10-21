"""Pruebo que el RiskAssessment del contrato y el JSON risk_details que guardaba el REST se traducen sin pérdida."""

import json
from pathlib import Path

import pytest
from kinesiapp.common.v1 import movement_pb2
from pydantic import ValidationError

from app.analysis.risk_assessment_codec import RiskAssessmentCodec, measurement_name, parse_measurement_name

# Lo generé con el RiskDetailsSerializer de kinesiapp-ai que usa el REST: un salto con dos ángulos sin medir
SAMPLE = json.loads((Path(__file__).parent / "risk_details_sample.json").read_text(encoding="utf-8"))


def test_the_json_of_the_rest_comes_back_identical_after_a_round_trip() -> None:
    codec = RiskAssessmentCodec()

    assessment = codec.to_assessment(SAMPLE, movement_pb2.RISK_LEVEL_HIGH)

    assert codec.to_details(assessment) == SAMPLE


def test_the_assessment_keeps_the_level_and_the_missing_measurements_as_absent_fields() -> None:
    assessment = RiskAssessmentCodec().to_assessment(SAMPLE, movement_pb2.RISK_LEVEL_HIGH)
    unmeasured = next(score for score in assessment.repetitions[1].signal_scores if score.code == "knee_deep")

    assert (assessment.risk_level, assessment.dominant_pattern) == (movement_pb2.RISK_LEVEL_HIGH, "forward_collapse")
    assert not unmeasured.HasField("score") and not unmeasured.HasField("measured_degrees")
    assert assessment.repetitions[0].detected_by == movement_pb2.DETECTION_METHOD_LANDING


def test_a_json_with_another_format_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RiskAssessmentCodec().to_assessment({**SAMPLE, "format_version": 2}, movement_pb2.RISK_LEVEL_LOW)


def _frontal() -> movement_pb2.RiskAssessment:
    signal = movement_pb2.RiskSignal(
        code="knee_valgus_right", joint=movement_pb2.JOINT_ANGLE_KNEE_VALGUS, side=movement_pb2.BODY_SIDE_RIGHT,
        direction=movement_pb2.RISK_DIRECTION_HIGHER_IS_RISKIER, onset_degrees=10.0, saturation_degrees=25.0, score_median=0.4,
        measured=movement_pb2.AngleSummary(median_degrees=16.0, min_degrees=12.0, max_degrees=19.0),
    )
    return movement_pb2.RiskAssessment(
        risk_score=0.4,
        risk_level=movement_pb2.RISK_LEVEL_MODERATE,
        dominant_pattern="knee_valgus_right",
        camera_view=movement_pb2.CAMERA_VIEW_FRONT,
        patterns=[movement_pb2.RiskPattern(code="knee_valgus_right", score=0.4, repetitions_triggered=1, signals=[signal])],
        repetitions=[
            movement_pb2.Repetition(
                start_ms=900, end_ms=1200, detected_by=movement_pb2.DETECTION_METHOD_HIP_BOTTOM,
                pattern_scores=[movement_pb2.RepetitionScore(code="knee_valgus_right", score=0.4)],
                signal_scores=[
                    movement_pb2.RepetitionScore(
                        code="knee_valgus_right", score=0.4, measured_degrees=16.0, side=movement_pb2.BODY_SIDE_RIGHT, peak_ms=1000
                    )
                ],
                keyframes=[
                    movement_pb2.PoseKeyframe(
                        timestamp_ms=1000,
                        keypoints=[
                            movement_pb2.Keypoint(landmark=movement_pb2.BODY_LANDMARK_RIGHT_HIP, x=0.43, y=0.5),
                            movement_pb2.Keypoint(landmark=movement_pb2.BODY_LANDMARK_RIGHT_KNEE, x=0.47, y=0.7),
                        ],
                    )
                ],
            )
        ],
    )


def test_a_frontal_assessment_keeps_its_view_legs_peaks_and_keyframes() -> None:
    codec = RiskAssessmentCodec()
    original = _frontal()
    assert codec.to_assessment(codec.to_details(original), movement_pb2.RISK_LEVEL_MODERATE) == original


def test_an_inconclusive_view_keeps_its_warning() -> None:
    codec = RiskAssessmentCodec()
    original = _frontal()
    original.camera_view = movement_pb2.CAMERA_VIEW_INCONCLUSIVE
    original.warnings.append(movement_pb2.ANALYSIS_WARNING_CAMERA_VIEW_INCONCLUSIVE)
    details = codec.to_details(original)
    assert (details["camera_view"], details["warnings"]) == ("inconclusive", ["camera_view_inconclusive"])
    assert codec.to_assessment(details, movement_pb2.RISK_LEVEL_MODERATE) == original


def test_an_old_json_has_no_view() -> None:
    assessment = RiskAssessmentCodec().to_assessment(SAMPLE, movement_pb2.RISK_LEVEL_HIGH)
    assert assessment.camera_view == movement_pb2.CAMERA_VIEW_UNSPECIFIED and not assessment.warnings


@pytest.mark.parametrize(
    ("joint", "side", "name"),
    [
        (movement_pb2.JOINT_ANGLE_KNEE_FLEXION, movement_pb2.BODY_SIDE_UNSPECIFIED, "knee_flexion"),
        (movement_pb2.JOINT_ANGLE_TRUNK_INCLINATION, movement_pb2.BODY_SIDE_UNSPECIFIED, "trunk_inclination"),
        (movement_pb2.JOINT_ANGLE_KNEE_VALGUS, movement_pb2.BODY_SIDE_LEFT, "knee_valgus_left"),
        (movement_pb2.JOINT_ANGLE_KNEE_VALGUS, movement_pb2.BODY_SIDE_RIGHT, "knee_valgus_right"),
    ],
)
def test_each_sample_is_stored_under_a_name_that_keeps_its_leg(joint, side, name) -> None:
    assert measurement_name(movement_pb2.JointAngleSample(joint=joint, side=side)) == name
    assert parse_measurement_name(name) == (joint, side)


def test_an_unknown_stored_name_reads_as_unspecified() -> None:
    assert parse_measurement_name("knee") == (movement_pb2.JOINT_ANGLE_UNSPECIFIED, movement_pb2.BODY_SIDE_UNSPECIFIED)
