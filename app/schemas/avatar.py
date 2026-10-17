import base64
import binascii
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.storage.image_formats import ImageFormat

MAX_AVATAR_BYTES = settings.MAX_AVATAR_UPLOAD_BYTES

AvatarContentType = Literal["image/jpeg", "image/png", "image/webp"]


class AvatarUpload(BaseModel):
    """Foto de perfil enviada como base64 en JSON (sin multipart)."""

    content_type: AvatarContentType
    data_base64: str = Field(min_length=1, max_length=(MAX_AVATAR_BYTES * 4) // 3 + 4)

    @model_validator(mode="after")
    def _check_image(self) -> "AvatarUpload":
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
        except binascii.Error as error:
            raise ValueError("data_base64 is not valid base64") from error
        if len(raw) > MAX_AVATAR_BYTES:
            raise ValueError("Avatar image is too large")
        if not ImageFormat.from_mime_type(self.content_type).matches(raw):
            raise ValueError("Image content does not match content_type")
        return self

    def content(self) -> bytes:
        # Ya validado como base64 en _check_image
        return base64.b64decode(self.data_base64)
