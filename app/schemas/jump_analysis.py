from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.jump_analysis import JumpAnalysisStatus, MovementType


class JointAngleMeasurementCreate(BaseModel):
    """Payload que envía el pipeline de IA por cada frame analizado."""

    joint_name: str = Field(min_length=1, max_length=50)
    angle_degrees: float = Field(ge=0, le=360)
    frame_timestamp_ms: int = Field(ge=0)


class JumpAnalysisResultIngest(BaseModel):
    """Resultado completo que la IA reporta al terminar de procesar un salto."""

    risk_score: float = Field(ge=0, le=1)
    measurements: list[JointAngleMeasurementCreate]
    dominant_risk_pattern: str | None = Field(default=None, max_length=50)
    risk_details: dict[str, Any] | None = None
    pose_model_version: str | None = Field(default=None, max_length=100)
    risk_model_version: str | None = Field(default=None, max_length=50)


class JointAngleMeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    joint_name: str
    angle_degrees: float
    frame_timestamp_ms: int


class JumpAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    athlete_id: int
    # Sin video_reference: es una ruta de disco del servidor y el cliente no la necesita
    movement_type: MovementType
    status: JumpAnalysisStatus
    risk_score: float | None
    dominant_risk_pattern: str | None
    pose_model_version: str | None
    risk_model_version: str | None
    recorded_at: datetime
    angle_measurements: list[JointAngleMeasurementRead] = []


class VideoAccessRead(BaseModel):
    """Token de corta vida para reproducir el video de un análisis."""

    token: str
    expires_at: datetime
