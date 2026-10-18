"""Pruebo los cortes del nivel de riesgo, incluidos los bordes."""

import pytest
from kinesiapp.common.v1 import movement_pb2

from app.analysis.risk_level import RiskLevelClassifier


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (None, movement_pb2.RISK_LEVEL_UNSPECIFIED),
        (0.0, movement_pb2.RISK_LEVEL_LOW),
        (0.329, movement_pb2.RISK_LEVEL_LOW),
        (0.33, movement_pb2.RISK_LEVEL_MODERATE),
        (0.66, movement_pb2.RISK_LEVEL_HIGH),
        (1.0, movement_pb2.RISK_LEVEL_HIGH),
    ],
)
def test_each_score_falls_in_its_level(score: float | None, level: int) -> None:
    assert RiskLevelClassifier(0.33, 0.66).level(score) == level


def test_cuts_out_of_order_are_rejected() -> None:
    with pytest.raises(ValueError):
        RiskLevelClassifier(moderate=0.7, high=0.5)
