from pathlib import Path

from pydantic import Field

from app.settings.base import EnvSettings

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


class PoseSettings(EnvSettings):
    """Extracción de pose y detección de la persona principal.

    La versión del modelo se guarda en cada análisis: cambiar de modelo exige cambiarla también.
    """

    POSE_MODEL_PATH: Path = _MODELS_DIR / "pose_landmarker_full.task"
    POSE_MODEL_VERSION: str = "mediapipe-pose_landmarker_full-float16-v1"
    POSE_MIN_DETECTION_CONFIDENCE: float = Field(default=0.5, ge=0, le=1)
    # Si otra persona compite con el atleta, MediaPipe solo ve el recorte del atleta (el más grande y
    # centrado) con este margen por lado. Las cajas por debajo del área relativa a la mayor no compiten:
    # el reflejo en el espejo de los videos de prueba ocupa hasta 0.19
    PERSON_DETECTOR_MODEL_PATH: Path = _MODELS_DIR / "yolo11n.onnx"
    PERSON_DETECTOR_MIN_CONFIDENCE: float = Field(default=0.5, ge=0, le=1)
    PERSON_CROP_MARGIN: float = Field(default=0.25, ge=0)
    PERSON_MIN_RELATIVE_AREA: float = Field(default=0.25, ge=0, le=1)
    # Seguimiento del atleta una vez que alguien compitió con él. En los videos de prueba su caja se solapa
    # al menos 0.24 con la anterior aun después de un hueco, y el detector lo pierde hasta 7 frames
    # seguidos en el vuelo por el desenfoque
    PERSON_TRACK_MIN_IOU: float = Field(default=0.2, gt=0, le=1)
    PERSON_TRACK_MAX_MISSED_FRAMES: int = Field(default=15, ge=0)
    PERSON_TRACK_SMOOTHING: float = Field(default=0.5, gt=0, le=1)
    LANDMARK_VISIBILITY_THRESHOLD: float = Field(default=0.1, ge=0, le=1)
    LANDMARK_SMOOTHING_WINDOW_FRAMES: int = Field(default=3, ge=1)


class MovementPhaseSettings(EnvSettings):
    """Detección de las repeticiones. Calibradas con un solo par de videos por ejercicio: no son definitivas."""

    JUMP_HIP_APEX_PROMINENCE: float = Field(default=0.08, gt=0)
    JUMP_HIP_APEX_MIN_DISTANCE_SECONDS: float = Field(default=0.6, gt=0)
    JUMP_APEX_AIRBORNE_BODY_FRACTION: float = Field(default=0.06, gt=0)
    JUMP_AIRBORNE_BODY_FRACTION: float = Field(default=0.03, gt=0)
    JUMP_GROUND_WINDOW_SECONDS: float = Field(default=1.0, gt=0)
    JUMP_GROUND_PERCENTILE: float = Field(default=90.0, ge=0, le=100)
    JUMP_LANDING_WINDOW_MS: int = Field(default=300, gt=0)
    JUMP_LANDING_END_MARGIN_FRAMES: int = Field(default=3, ge=0)
    SQUAT_BOTTOM_MIN_PROMINENCE_DEG: float = Field(default=25.0, gt=0)
    SQUAT_BOTTOM_MIN_FLEXION_DEG: float = Field(default=50.0, ge=0)
    SQUAT_BOTTOM_MIN_DISTANCE_SECONDS: float = Field(default=0.6, gt=0)
    SQUAT_BOTTOM_WINDOW_MS: int = Field(default=200, ge=0)
    # Respaldo cuando la rodilla no deja picos (bisagra de cadera con piernas casi rectas): el umbral de
    # tronco es RISK_SQUAT_TRUNK_LEAN_ONSET_DEG, el mismo donde empieza el riesgo
    SQUAT_HINGE_MIN_DURATION_SECONDS: float = Field(default=0.3, gt=0)
