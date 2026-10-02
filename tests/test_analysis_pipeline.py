"""JumpVideoAnalyzer de punta a punta con un extractor falso (sin MediaPipe ni video real)."""
from pathlib import Path

import pytest

from app.analysis.angles import AngleCalculator
from app.analysis.errors import NoMovementDetectedError, UnreadableVideoError
from app.analysis.pose_extraction import VideoPoseExtractor
from app.analysis.pose_series import PoseSeries
from app.analysis.preprocessing import LandmarkSeriesPreprocessor
from app.analysis.risk_details import RiskDetailsSerializer
from app.analysis.video_reader import VideoFrameReader
from app.core.config import settings
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus, MovementType
from app.services.jump_analysis_processor import (
    KNEE_FLEXION_JOINT,
    TRUNK_INCLINATION_JOINT,
    JumpAnalysisProcessor,
    JumpVideoAnalyzer,
)
from app.services.jump_video_analyzer_factory import build_jump_risk_profile, build_squat_risk_profile
from tests.conftest import TestingSessionLocal
from tests.pose_fixtures import add_hip_hinge, add_jump, pose_series, standing_points


class _FixedPoseExtractor:
    def __init__(self, series: PoseSeries) -> None:
        self._series = series

    def extract(self, video_path: Path) -> PoseSeries:
        return self._series


def _analyzer(pose_extractor) -> JumpVideoAnalyzer:
    return JumpVideoAnalyzer(
        pose_extractor=pose_extractor,
        preprocessor=LandmarkSeriesPreprocessor(settings.LANDMARK_VISIBILITY_THRESHOLD, settings.LANDMARK_SMOOTHING_WINDOW_FRAMES),
        angle_calculator=AngleCalculator(),
        profiles={
            MovementType.JUMP: build_jump_risk_profile(settings),
            MovementType.SQUAT: build_squat_risk_profile(settings),
        },
        risk_details_serializer=RiskDetailsSerializer(),
        pose_model_version="pose-test-v1",
        risk_model_version="risk-test-v1",
    )


def _jump_series() -> PoseSeries:
    points = standing_points(90)
    add_jump(points, takeoff=30, landing=45, height=0.15)
    return pose_series(points)


def test_result_carries_versions_and_one_measurement_per_frame_and_joint():
    result = _analyzer(_FixedPoseExtractor(_jump_series())).analyze(Path("jump.mp4"), MovementType.JUMP)
    assert (result.pose_model_version, result.risk_model_version) == ("pose-test-v1", "risk-test-v1")
    assert 0 <= result.risk_score <= 1
    joints = {m.joint_name for m in result.measurements}
    assert joints <= {KNEE_FLEXION_JOINT, TRUNK_INCLINATION_JOINT}
    timestamps = [m.frame_timestamp_ms for m in result.measurements if m.joint_name == TRUNK_INCLINATION_JOINT]
    assert timestamps == sorted(timestamps) and len(timestamps) == 90


def test_video_without_the_movement_is_rejected():
    analyzer = _analyzer(_FixedPoseExtractor(pose_series(standing_points(90))))
    with pytest.raises(NoMovementDetectedError):
        analyzer.analyze(Path("still.mp4"), MovementType.JUMP)


def test_straight_leg_hip_hinge_is_high_risk_instead_of_failing():
    points = standing_points(90)
    add_hip_hinge(points, start=30, end=60)
    result = _analyzer(_FixedPoseExtractor(pose_series(points))).analyze(Path("hinge.mp4"), MovementType.SQUAT)
    assert result.dominant_risk_pattern == "hip_hinge_squat"
    assert result.risk_score == 1


def test_unreadable_file_fails_before_loading_the_pose_model(tmp_path):
    not_a_video = tmp_path / "garbage.mp4"
    not_a_video.write_bytes(b"not a video")

    def estimator_must_not_be_created():
        raise AssertionError("the pose model was loaded for an unreadable file")

    analyzer = _analyzer(VideoPoseExtractor(VideoFrameReader(), estimator_must_not_be_created))
    with pytest.raises(UnreadableVideoError):
        analyzer.analyze(not_a_video, MovementType.JUMP)


def test_processor_marks_failed_when_the_movement_is_not_found(db_session):
    analysis = JumpAnalysis(athlete_id=1, video_reference="still.mp4", movement_type=MovementType.SQUAT)
    db_session.add(analysis)
    db_session.commit()
    analyzer = _analyzer(_FixedPoseExtractor(pose_series(standing_points(90))))

    JumpAnalysisProcessor(TestingSessionLocal, analyzer).process(analysis.id)

    db_session.refresh(analysis)
    assert analysis.status == JumpAnalysisStatus.FAILED
    assert analysis.risk_score is None
