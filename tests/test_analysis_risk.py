"""Patrones de riesgo con los umbrales configurados por defecto en Settings (§5.2 y §5.6)."""
import pytest

from kinesiapp_ai.analysis.movement_windows import DetectionMethod, MovementWindow

from app.core.config import settings
from app.services.jump_video_analyzer_factory import build_jump_risk_profile, build_squat_risk_profile
from tests.pose_fixtures import angle_series

WHOLE = MovementWindow(0, 2, DetectionMethod.LANDING)


# Criterios de aceptación de la Fase 4 (§11) con los umbrales configurados por defecto
@pytest.mark.parametrize(
    ("knee_flexion", "trunk_inclination", "expected_pattern"),
    [
        (20, 5, "rigid_landing"),
        (110, 60, "forward_collapse"),
        (110, 5, None),
    ],
    ids=["rigid", "collapse", "deep-but-upright"],
)
def test_default_jump_patterns(knee_flexion, trunk_inclination, expected_pattern):
    aggregator = build_jump_risk_profile(settings).aggregator
    risk = aggregator.aggregate(angle_series([knee_flexion] * 3, [trunk_inclination] * 3), [WHOLE])
    assert risk.dominant_pattern == expected_pattern
    assert (risk.risk_score > 0) == (expected_pattern is not None)


@pytest.mark.parametrize(
    ("knee_flexion", "trunk_inclination", "expected_pattern"),
    [
        # Como sentadilla_mal_echa: se dobla por la cadera en vez de por la rodilla
        (65, 105, "hip_hinge_squat"),
        # Como sentadilla_bien_echa: profunda, el tronco acompaña
        (105, 58, None),
        (100, 105, None),
        (65, 20, None),
    ],
    ids=["hip-hinge", "deep-good", "deep-and-leaning", "shallow-upright"],
)
def test_default_squat_pattern_is_trunk_lean_without_knee_flexion(knee_flexion, trunk_inclination, expected_pattern):
    aggregator = build_squat_risk_profile(settings).aggregator
    risk = aggregator.aggregate(angle_series([knee_flexion] * 3, [trunk_inclination] * 3), [WHOLE])
    assert risk.dominant_pattern == expected_pattern
