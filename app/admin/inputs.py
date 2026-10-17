from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.core.input_rules import InputModel, parse_input, rules_of
from app.identity.password_policy import PasswordPolicy
from app.models.user import UserRole
from app.schemas.person_name import PersonName


@dataclass(frozen=True)
class AdminInputRules:
    password_policy: PasswordPolicy

    def parse(self, model: type[InputModel], data: dict[str, Any]) -> InputModel:
        return parse_input(model, data, self)


class NewUserInput(BaseModel):
    email: EmailStr
    password: str
    full_name: PersonName
    # Como en el registro público: ADMIN solo se asigna después, cambiando el rol
    role: Literal[UserRole.ATHLETE, UserRole.COACH]

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: str, info: ValidationInfo) -> str:
        return rules_of(info, AdminInputRules).password_policy.ensure_valid(value)


class UserIdInput(BaseModel):
    user_id: int = Field(gt=0)


class RoleChangeInput(UserIdInput):
    role: UserRole


class StatusChangeInput(UserIdInput):
    is_active: bool
