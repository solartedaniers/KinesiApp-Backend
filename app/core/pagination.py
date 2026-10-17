import base64
import binascii
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.core.input_rules import parse_input, rules_of
from app.settings.pagination import PaginationSettings


@dataclass(frozen=True)
class PageRules:
    """Tamaños de página de los listados por cursor, compartidos por todos los servicios."""

    default_size: int
    max_size: int

    @classmethod
    def from_settings(cls, settings: PaginationSettings) -> "PageRules":
        return cls(settings.PAGE_SIZE_DEFAULT, settings.PAGE_SIZE_MAX)

    def parse(self, page_size: int, page_token: str) -> "PageInput":
        return parse_input(PageInput, {"page_size": page_size, "page_token": page_token}, self)


class PageInput(BaseModel):
    limit: int = Field(validation_alias="page_size")
    after_id: int = Field(validation_alias="page_token")

    @field_validator("limit")
    @classmethod
    def _bounded(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError("Page size cannot be negative")
        rules = rules_of(info, PageRules)
        return min(value or rules.default_size, rules.max_size)

    @field_validator("after_id", mode="before")
    @classmethod
    def _decoded(cls, value: Any) -> int:
        return decode_page_token(value)


def encode_page_token(last_id: int) -> str:
    # Opaco para que el cliente no arme cursores a mano, pero sin estado en el servidor
    return base64.urlsafe_b64encode(str(last_id).encode()).decode()


def decode_page_token(token: str) -> int:
    if not token:
        return 0
    try:
        last_id = int(base64.urlsafe_b64decode(token.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ValueError("Invalid page token") from error
    if last_id <= 0:
        raise ValueError("Invalid page token")
    return last_id
