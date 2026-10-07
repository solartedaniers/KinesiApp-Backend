"""Pipeline completo, con MediaPipe real, sobre los videos propios del spike.

Los videos y los modelos no se versionan (spikes/pose_spike/videos/, models/): sin ellos estos
tests se saltan. Los nombres de archivo son la verdad: "bien" es la técnica correcta y "mal" la
incorrecta. También comprueban que dos corridas sobre el mismo video dan exactamente lo mismo.
"""
from pathlib import Path

import cv2
import pytest

from app.core.config import settings
from app.models.jump_analysis import MovementType
from app.services.jump_video_analyzer_factory import build_jump_video_analyzer

VIDEOS_DIR = Path(__file__).resolve().parents[1] / "spikes" / "pose_spike" / "videos"
VIDEOS = {
    "salto_bien_echo.mp4": MovementType.JUMP,
    "salto_mal_echo.mp4": MovementType.JUMP,
    "sentadilla_bien_echa.mp4": MovementType.SQUAT,
    "sentadilla_mal_echa.mp4": MovementType.SQUAT,
}
LOW_RISK = 0.33

pytestmark = pytest.mark.skipif(
    not settings.POSE_MODEL_PATH.is_file()
    or not settings.PERSON_DETECTOR_MODEL_PATH.is_file()
    or not all((VIDEOS_DIR / name).is_file() for name in VIDEOS),
    reason="Pose or person-detection model, or spike videos, not available locally",
)


@pytest.fixture(scope="module")
def crossing_video(tmp_path_factory):
    """salto_mal con otra persona (recortada de sentadilla_mal, de pie) cruzando por delante de
    izquierda a derecha durante casi todo el video."""
    athlete = cv2.VideoCapture(str(VIDEOS_DIR / "salto_mal_echo.mp4"))
    fps = athlete.get(cv2.CAP_PROP_FPS)
    frames = []
    while (read := athlete.read())[0]:
        frames.append(read[1])
    athlete.release()
    passerby_source = cv2.VideoCapture(str(VIDEOS_DIR / "sentadilla_mal_echa.mp4"))
    passerby = cv2.resize(passerby_source.read()[1][300:850, 90:430], None, fx=0.6, fy=0.6)
    passerby_source.release()

    path = tmp_path_factory.mktemp("crossing") / "salto_mal_con_cruce.mp4"
    height, width = frames[0].shape[:2]
    patch_height, patch_width = passerby.shape[:2]
    start, end = 20, len(frames) - 10
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for index, frame in enumerate(frames):
        if start <= index < end:
            x = round(-patch_width + (width + patch_width) * (index - start) / (end - start))
            x1, x2 = max(0, x), min(width, x + patch_width)
            if x2 > x1:
                frame[height - patch_height :, x1:x2] = passerby[:, x1 - x : x2 - x]
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture(scope="module")
def results():
    analyzer = build_jump_video_analyzer(settings)
    return {name: analyzer.analyze(VIDEOS_DIR / name, movement) for name, movement in VIDEOS.items()}


def test_bad_jump_is_a_forward_collapse_and_the_good_one_is_low_risk(results):
    good, bad = results["salto_bien_echo.mp4"], results["salto_mal_echo.mp4"]
    assert good.risk_score < LOW_RISK < bad.risk_score
    assert bad.dominant_risk_pattern == "forward_collapse"


def test_bad_squat_is_a_hip_hinge_and_the_good_one_is_low_risk(results):
    good, bad = results["sentadilla_bien_echa.mp4"], results["sentadilla_mal_echa.mp4"]
    assert good.risk_score < LOW_RISK < bad.risk_score
    assert bad.dominant_risk_pattern == "hip_hinge_squat"


def test_results_record_the_model_and_rule_versions(results):
    for result in results.values():
        assert (result.pose_model_version, result.risk_model_version) == (
            settings.POSE_MODEL_VERSION,
            settings.RISK_MODEL_VERSION,
        )


def test_same_video_gives_the_same_result(results):
    rerun = build_jump_video_analyzer(settings).analyze(VIDEOS_DIR / "salto_mal_echo.mp4", MovementType.JUMP)
    assert rerun == results["salto_mal_echo.mp4"]


def test_risk_details_explain_the_bad_jump_and_squat_with_measured_values(results):
    jump = results["salto_mal_echo.mp4"].risk_details
    collapse = jump["patterns"]["forward_collapse"]
    assert collapse["repetitions_triggered"] == jump["repetitions_evaluated"] > 0
    assert collapse["signals"]["knee_deep"]["measured_deg"]["median"] > settings.RISK_JUMP_KNEE_DEEP_ONSET_DEG
    assert collapse["signals"]["trunk_lean"]["measured_deg"]["median"] > settings.RISK_JUMP_TRUNK_LEAN_ONSET_DEG

    squat = results["sentadilla_mal_echa.mp4"].risk_details
    hinge = squat["patterns"]["hip_hinge_squat"]
    assert squat["detection_methods"] == {"knee_bottom": squat["repetitions_evaluated"]}
    assert hinge["signals"]["squat_trunk_lean"]["measured_deg"]["min"] > settings.RISK_SQUAT_TRUNK_LEAN_ONSET_DEG
    assert hinge["signals"]["squat_knee_shallow"]["direction"] == "lower_is_riskier"


@pytest.mark.xfail(
    strict=True,
    reason="Caso límite abierto: mientras YOLO pierde al atleta en el vuelo (desenfoque), el que cruza "
    "pasa por debajo de la región sostenida, la solapa más que el umbral de IoU y se queda con el seguimiento",
)
def test_someone_crossing_does_not_change_the_bad_jump_result(results, crossing_video):
    crossed = build_jump_video_analyzer(settings).analyze(crossing_video, MovementType.JUMP)
    original = results["salto_mal_echo.mp4"]
    assert crossed.dominant_risk_pattern == original.dominant_risk_pattern == "forward_collapse"
    assert crossed.risk_details["repetitions_evaluated"] == original.risk_details["repetitions_evaluated"]
