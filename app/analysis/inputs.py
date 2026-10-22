from dataclasses import dataclass

from kinesiapp.common.v1 import movement_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from pydantic import BaseModel, Field, field_validator

from app.core.domain_error import DomainError
from app.models.jump_analysis import MovementType


class AnalysisIdInput(BaseModel):
    analysis_id: int = Field(gt=0)


class UploadIdInput(BaseModel):
    upload_id: str = Field(min_length=1)


class VideoUploadInput(BaseModel):
    athlete_id: int = Field(gt=0)
    movement_type: MovementType
    content_type: str
    content_length: int
    duration_ms: int

    @field_validator("movement_type", mode="before")
    @classmethod
    def _from_proto(cls, value: object) -> object:
        # Con MOVEMENT_TYPE_UNSPECIFIED devuelvo None y el validador lo reporta como campo inválido
        if isinstance(value, int):
            return MovementType.__members__.get(movement_pb2.MovementType.Name(value).removeprefix("MOVEMENT_TYPE_"))
        return value


@dataclass(frozen=True)
class VideoUploadRules:
    """Aplico los límites del video que también valida el cliente. Respondo con los reason del contrato, no con un
    campo inválido, para que el frontend muestre el mensaje exacto."""

    max_bytes: int
    max_duration_ms: int

    def check(self, upload: VideoUploadInput) -> None:
        if not upload.content_type.startswith("video/") or upload.content_length <= 0 or upload.duration_ms <= 0:
            raise DomainError(ErrorReason.ERROR_REASON_INVALID_VIDEO, "The file is not a video")
        if upload.content_length > self.max_bytes:
            raise DomainError(ErrorReason.ERROR_REASON_VIDEO_TOO_LARGE, "The video is larger than allowed")
        if upload.duration_ms > self.max_duration_ms:
            raise DomainError(ErrorReason.ERROR_REASON_VIDEO_TOO_LONG, "The video is longer than allowed")
