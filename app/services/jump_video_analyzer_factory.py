from functools import lru_cache, partial

from kinesiapp_ai.analysis.angles import AngleCalculator
from kinesiapp_ai.analysis.jump_phases import JumpPhaseDetector
from kinesiapp_ai.analysis.person_detection import YoloPersonDetector
from kinesiapp_ai.analysis.pose_estimator import MediaPipePoseEstimator
from kinesiapp_ai.analysis.pose_extraction import MainPersonCropper, VideoPoseExtractor
from kinesiapp_ai.analysis.preprocessing import LandmarkSeriesPreprocessor
from kinesiapp_ai.analysis.risk import KneeFlexionRiskStrategy, LinearRamp, RiskScoreAggregator, TrunkFlexionRiskStrategy
from kinesiapp_ai.analysis.risk_details import RiskDetailsSerializer
from kinesiapp_ai.analysis.squat_phases import SquatBottomDetector
from kinesiapp_ai.analysis.trunk_hinge import FallbackWindowDetector, TrunkHingeDetector
from kinesiapp_ai.analysis.video_reader import VideoFrameReader

from app.core.config import Settings, settings
from app.models.jump_analysis import MovementType
from app.services.jump_analysis_processor import JumpVideoAnalyzer, MovementRiskProfile


def build_jump_video_analyzer(config: Settings) -> JumpVideoAnalyzer:
    return JumpVideoAnalyzer(
        pose_extractor=VideoPoseExtractor(
            VideoFrameReader(),
            partial(MediaPipePoseEstimator, config.POSE_MODEL_PATH, config.POSE_MIN_DETECTION_CONFIDENCE),
            MainPersonCropper(
                YoloPersonDetector(config.PERSON_DETECTOR_MODEL_PATH, config.PERSON_DETECTOR_MIN_CONFIDENCE),
                margin=config.PERSON_CROP_MARGIN,
                min_relative_area=config.PERSON_MIN_RELATIVE_AREA,
            ),
        ),
        preprocessor=LandmarkSeriesPreprocessor(
            config.LANDMARK_VISIBILITY_THRESHOLD, config.LANDMARK_SMOOTHING_WINDOW_FRAMES
        ),
        angle_calculator=AngleCalculator(),
        profiles={
            MovementType.JUMP: build_jump_risk_profile(config),
            MovementType.SQUAT: build_squat_risk_profile(config),
        },
        risk_details_serializer=RiskDetailsSerializer(),
        pose_model_version=config.POSE_MODEL_VERSION,
        risk_model_version=config.RISK_MODEL_VERSION,
    )


def build_jump_risk_profile(config: Settings) -> MovementRiskProfile:
    return MovementRiskProfile(
        window_detector=JumpPhaseDetector(
            hip_apex_prominence=config.JUMP_HIP_APEX_PROMINENCE,
            hip_apex_min_distance_seconds=config.JUMP_HIP_APEX_MIN_DISTANCE_SECONDS,
            apex_airborne_body_fraction=config.JUMP_APEX_AIRBORNE_BODY_FRACTION,
            airborne_body_fraction=config.JUMP_AIRBORNE_BODY_FRACTION,
            ground_window_seconds=config.JUMP_GROUND_WINDOW_SECONDS,
            ground_percentile=config.JUMP_GROUND_PERCENTILE,
            landing_window_ms=config.JUMP_LANDING_WINDOW_MS,
            landing_end_margin_frames=config.JUMP_LANDING_END_MARGIN_FRAMES,
        ),
        aggregator=RiskScoreAggregator(
            strategies=[
                KneeFlexionRiskStrategy({
                    "knee_rigid": LinearRamp(config.RISK_JUMP_KNEE_RIGID_ONSET_DEG, config.RISK_JUMP_KNEE_RIGID_SATURATION_DEG),
                    "knee_deep": LinearRamp(config.RISK_JUMP_KNEE_DEEP_ONSET_DEG, config.RISK_JUMP_KNEE_DEEP_SATURATION_DEG),
                }),
                TrunkFlexionRiskStrategy({
                    "trunk_lean": LinearRamp(config.RISK_JUMP_TRUNK_LEAN_ONSET_DEG, config.RISK_JUMP_TRUNK_LEAN_SATURATION_DEG),
                }),
            ],
            patterns=config.RISK_JUMP_PATTERNS,
        ),
    )


def build_squat_risk_profile(config: Settings) -> MovementRiskProfile:
    return MovementRiskProfile(
        window_detector=FallbackWindowDetector([
            SquatBottomDetector(
                min_prominence_deg=config.SQUAT_BOTTOM_MIN_PROMINENCE_DEG,
                min_flexion_deg=config.SQUAT_BOTTOM_MIN_FLEXION_DEG,
                min_distance_seconds=config.SQUAT_BOTTOM_MIN_DISTANCE_SECONDS,
                window_ms=config.SQUAT_BOTTOM_WINDOW_MS,
            ),
            TrunkHingeDetector(
                min_trunk_inclination_deg=config.RISK_SQUAT_TRUNK_LEAN_ONSET_DEG,
                min_duration_seconds=config.SQUAT_HINGE_MIN_DURATION_SECONDS,
                window_ms=config.SQUAT_BOTTOM_WINDOW_MS,
            ),
        ]),
        aggregator=RiskScoreAggregator(
            strategies=[
                KneeFlexionRiskStrategy({
                    "squat_knee_shallow": LinearRamp(
                        config.RISK_SQUAT_KNEE_SHALLOW_ONSET_DEG, config.RISK_SQUAT_KNEE_SHALLOW_SATURATION_DEG
                    ),
                }),
                TrunkFlexionRiskStrategy({
                    "squat_trunk_lean": LinearRamp(config.RISK_SQUAT_TRUNK_LEAN_ONSET_DEG, config.RISK_SQUAT_TRUNK_LEAN_SATURATION_DEG),
                }),
            ],
            patterns=config.RISK_SQUAT_PATTERNS,
        ),
    )


@lru_cache
def get_jump_video_analyzer() -> JumpVideoAnalyzer:
    # Sin estado por video (el estimador se crea en cada extracción): se arma una sola vez
    return build_jump_video_analyzer(settings)
