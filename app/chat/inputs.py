from dataclasses import dataclass
from typing import Any

from pydantic import ValidationInfo, field_validator

from app.analysis.inputs import AnalysisIdInput
from app.core.input_rules import InputModel, parse_input, rules_of


@dataclass(frozen=True)
class ChatInputRules:
    max_message_chars: int

    def parse(self, model: type[InputModel], data: dict[str, Any]) -> InputModel:
        return parse_input(model, data, self)


class QuestionInput(AnalysisIdInput):
    content: str

    @field_validator("content")
    @classmethod
    def _within_limit(cls, value: str, info: ValidationInfo) -> str:
        limit = rules_of(info, ChatInputRules).max_message_chars
        stripped = value.strip()
        if not 0 < len(stripped) <= limit:
            raise ValueError(f"The message must have between 1 and {limit} characters")
        return stripped
