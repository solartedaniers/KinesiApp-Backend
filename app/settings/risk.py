from pydantic import Field

from app.settings.base import EnvSettings


class RiskSettings(EnvSettings):
    """Umbrales de riesgo: placeholders de orden de magnitud tomados del spike, SIN validación clínica.

    Cada parcial es una rampa de "onset" (0) a "saturation" (1).
    """

    RISK_MODEL_VERSION: str = "risk-patterns-v1"
    RISK_JUMP_KNEE_RIGID_ONSET_DEG: float = 60.0
    RISK_JUMP_KNEE_RIGID_SATURATION_DEG: float = 30.0
    RISK_JUMP_KNEE_DEEP_ONSET_DEG: float = 80.0
    RISK_JUMP_KNEE_DEEP_SATURATION_DEG: float = 100.0
    RISK_JUMP_TRUNK_LEAN_ONSET_DEG: float = 25.0
    RISK_JUMP_TRUNK_LEAN_SATURATION_DEG: float = 45.0
    RISK_JUMP_PATTERNS: dict[str, list[str]] = {
        "rigid_landing": ["knee_rigid"],
        "forward_collapse": ["knee_deep", "trunk_lean"],
        "trunk_lean": ["trunk_lean"],
    }
    # Sentadilla: el riesgo es inclinar el tronco EN LUGAR de flexionar la rodilla (rampa de rodilla
    # descendente: menos flexión, más riesgo)
    RISK_SQUAT_KNEE_SHALLOW_ONSET_DEG: float = 90.0
    RISK_SQUAT_KNEE_SHALLOW_SATURATION_DEG: float = 80.0
    RISK_SQUAT_TRUNK_LEAN_ONSET_DEG: float = 70.0
    RISK_SQUAT_TRUNK_LEAN_SATURATION_DEG: float = 90.0
    RISK_SQUAT_PATTERNS: dict[str, list[str]] = {
        "hip_hinge_squat": ["squat_trunk_lean", "squat_knee_shallow"],
    }
    # Cortes de nivel de riesgo: con nivel "high" el chat recomienda consulta profesional
    RISK_LEVEL_MODERATE: float = Field(default=0.33, ge=0, le=1)
    RISK_LEVEL_HIGH: float = Field(default=0.66, ge=0, le=1)
