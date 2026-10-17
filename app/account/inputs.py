from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator

from app.core.input_rules import InputModel, parse_input, rules_of
from app.schemas.person_name import PersonName
from app.storage.image_formats import ImageFormat


@dataclass(frozen=True)
class AccountInputRules:
    max_avatar_bytes: int

    def parse(self, model: type[InputModel], data: dict[str, Any]) -> InputModel:
        return parse_input(model, data, self)


class ProfileInput(BaseModel):
    full_name: PersonName


class AvatarUploadInput(BaseModel):
    image_format: ImageFormat
    content_length: int

    @field_validator("content_length")
    @classmethod
    def _within_limit(cls, value: int, info: ValidationInfo) -> int:
        limit = rules_of(info, AccountInputRules).max_avatar_bytes
        if not 0 < value <= limit:
            raise ValueError(f"Avatar must have between 1 and {limit} bytes")
        return value


class VideoConsentInput(BaseModel):
    version: int
