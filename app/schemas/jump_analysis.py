from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.jump_analysis import JumpAnalysisStatus


class JumpAnalysisCreate(BaseModel):
    athlete_id: int
    video_reference: str = Field(min_length=1, max_length=500)


class JointAngleMeasurementCreate(BaseModel):
    """Payload que envía el pipeline de IA por cada frame analizado."""

    joint_name: str = Field(min_length=1, max_length=50)
    angle_degrees: float = Field(ge=0, le=360)
    frame_timestamp_ms: int = Field(ge=0)


class JumpAnalysisResultIngest(BaseModel):
    """Resultado completo que la IA reporta al terminar de procesar un salto."""

    risk_score: float = Field(ge=0, le=1)
    measurements: list[JointAngleMeasurementCreate]


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
    video_reference: str
    status: JumpAnalysisStatus
    risk_score: float | None
    recorded_at: datetime
    angle_measurements: list[JointAngleMeasurementRead] = []
