"""risk_details: el desglose del riesgo que se persiste para que el chat explique el resultado."""
import json
import math
from pathlib import Path

from app.analysis.movement_windows import DetectionMethod, MovementWindow
from app.analysis.risk_details import RISK_DETAILS_FORMAT_VERSION, RiskDetailsSerializer
from app.core.config import settings
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus, MovementType
from app.services.jump_analysis_processor import JumpAnalysisProcessor
from app.services.jump_video_analyzer_factory import build_jump_risk_profile, build_squat_risk_profile
from tests.conftest import TestingSessionLocal
from tests.pose_fixtures import FPS, add_hip_hinge, add_jump, angle_series, pose_series, standing_points
from tests.test_analysis_pipeline import _analyzer, _FixedPoseExtractor


def _details(profile, knee_flexion, trunk_inclination, windows):
    angles = angle_series(knee_flexion, trunk_inclination)
    risk = profile.aggregator.aggregate(angles, windows)
    return RiskDetailsSerializer().serialize(risk, pose_series(standing_points(len(knee_flexion))))


def _landings(*frames: int) -> list[MovementWindow]:
    return [MovementWindow(frame, frame, DetectionMethod.LANDING) for frame in frames]


def test_jump_collapse_records_each_signal_with_its_measurement_threshold_and_direction():
    details = _details(build_jump_risk_profile(settings), [100, 110, 119], [59, 72, 20], _landings(0, 1, 2))
    collapse = details["patterns"]["forward_collapse"]
    knee, trunk = collapse["signals"]["knee_deep"], collapse["signals"]["trunk_lean"]

    assert details["dominant_pattern"] == "forward_collapse"
    assert details["format_version"] == RISK_DETAILS_FORMAT_VERSION
    assert knee == {
        "signal": "knee_flexion",
        "direction": "higher_is_riskier",
        "onset_deg": settings.RISK_JUMP_KNEE_DEEP_ONSET_DEG,
        "saturation_deg": settings.RISK_JUMP_KNEE_DEEP_SATURATION_DEG,
        "measured_deg": {"median": 110, "min": 100, "max": 119},
        "score_median": 1.0,
    }
    assert trunk["signal"] == "trunk_inclination"
    assert trunk["measured_deg"] == {"median": 59, "min": 20, "max": 72}
    # La tercera repetición tiene el tronco erguido: no dispara el colapso
    assert collapse["repetitions_triggered"] == 2
    assert details["repetitions_evaluated"] == 3
    assert details["detection_methods"] == {"landing": 3}


def test_rigid_landing_signal_is_lower_is_riskier():
    details = _details(build_jump_risk_profile(settings), [20, 25], [5, 5], _landings(0, 1))
    rigid = details["patterns"]["rigid_landing"]
    assert details["dominant_pattern"] == "rigid_landing"
    assert rigid["signals"]["knee_rigid"]["direction"] == "lower_is_riskier"
    assert rigid["repetitions_triggered"] == 2
    assert details["patterns"]["forward_collapse"]["repetitions_triggered"] == 0


def test_each_repetition_keeps_its_time_window_detection_and_values():
    windows = [MovementWindow(3, 9, DetectionMethod.KNEE_BOTTOM)]
    details = _details(build_squat_risk_profile(settings), [0] * 3 + [65] * 7, [0] * 3 + [105] * 7, windows)
    (repetition,) = details["repetitions"]
    assert repetition["start_ms"] == round(3 * 1000 / FPS)
    assert repetition["end_ms"] == round(9 * 1000 / FPS)
    assert repetition["detected_by"] == "knee_bottom"
    assert repetition["pattern_scores"] == {"hip_hinge_squat": 1.0}
    assert repetition["partials"]["squat_knee_shallow"] == {"measured_deg": 65, "score": 1.0}
    assert repetition["partials"]["squat_trunk_lean"] == {"measured_deg": 105, "score": 1.0}


def test_missing_signal_is_null_and_the_result_is_strict_json():
    details = _details(build_jump_risk_profile(settings), [math.nan, math.nan], [30, 40], _landings(0, 1))
    knee = details["patterns"]["forward_collapse"]["signals"]["knee_deep"]
    assert knee["measured_deg"] is None and knee["score_median"] is None
    assert details["patterns"]["forward_collapse"]["score"] is None
    # Postgres rechaza NaN en JSON: tiene que serializar sin él
    json.dumps(details, allow_nan=False)


def test_trunk_hinge_fallback_is_recorded_as_the_detection_method():
    points = standing_points(90)
    add_hip_hinge(points, start=30, end=60)
    result = _analyzer(_FixedPoseExtractor(pose_series(points))).analyze(Path("hinge.mp4"), MovementType.SQUAT)
    details = result.risk_details
    hinge = details["patterns"]["hip_hinge_squat"]

    assert details["detection_methods"] == {"trunk_hinge": 1}
    assert details["repetitions"][0]["detected_by"] == "trunk_hinge"
    assert hinge["repetitions_triggered"] == 1
    assert hinge["signals"]["squat_knee_shallow"]["measured_deg"]["median"] < settings.RISK_SQUAT_KNEE_SHALLOW_SATURATION_DEG
    assert hinge["signals"]["squat_trunk_lean"]["measured_deg"]["median"] >= settings.RISK_SQUAT_TRUNK_LEAN_SATURATION_DEG


def test_processor_persists_risk_details(db_session):
    points = standing_points(90)
    add_jump(points, takeoff=30, landing=45, height=0.15)
    analysis = JumpAnalysis(athlete_id=1, video_reference="jump.mp4", movement_type=MovementType.JUMP)
    db_session.add(analysis)
    db_session.commit()

    JumpAnalysisProcessor(TestingSessionLocal, _analyzer(_FixedPoseExtractor(pose_series(points)))).process(analysis.id)

    db_session.refresh(analysis)
    assert analysis.status == JumpAnalysisStatus.PROCESSED
    assert analysis.risk_details["detection_methods"] == {"landing": 1}
    assert set(analysis.risk_details["patterns"]) == set(settings.RISK_JUMP_PATTERNS)
