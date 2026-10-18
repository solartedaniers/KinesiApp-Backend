"""Pruebo que el RiskAssessment del contrato y el JSON risk_details que guardaba el REST se traducen sin pérdida."""

import json
from pathlib import Path

import pytest
from kinesiapp.common.v1 import movement_pb2
from pydantic import ValidationError

from app.analysis.risk_assessment_codec import RiskAssessmentCodec

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
