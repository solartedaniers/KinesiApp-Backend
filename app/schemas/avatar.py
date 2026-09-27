import base64
import binascii
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ponytail: el avatar se guarda como data URL en la DB (imágenes chicas, ya
# redimensionadas por la app); pasar a object storage (S3/GCS) si crecen
MAX_AVATAR_BYTES = 1_000_000

AvatarContentType = Literal["image/jpeg", "image/png", "image/webp"]


def _matches_signature(content_type: str, raw: bytes) -> bool:
    # Magic bytes: el content_type declarado debe coincidir con el contenido real
    if content_type == "image/jpeg":
        return raw.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"


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
        if not _matches_signature(self.content_type, raw):
            raise ValueError("Image content does not match content_type")
        return self

    def to_data_url(self) -> str:
        return f"data:{self.content_type};base64,{self.data_base64}"
