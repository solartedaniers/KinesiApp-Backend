from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.core.input_rules import InputModel, parse_input, rules_of
from app.identity.password_policy import PasswordPolicy
from app.models.user import UserRole
from app.identity.person_name import PersonName


@dataclass(frozen=True)
class AdminInputRules:
    password_policy: PasswordPolicy

    def parse(self, model: type[InputModel], data: dict[str, Any]) -> InputModel:
        return parse_input(model, data, self)


class AccountInput(BaseModel):
    email: EmailStr
    password: str
    full_name: PersonName

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: str, info: ValidationInfo) -> str:
        return rules_of(info, AdminInputRules).password_policy.ensure_valid(value)


class NewUserInput(AccountInput):
    # Como en el registro público, aquí no admito ADMIN: ese rol solo se asigna después, cambiando el rol
    role: Literal[UserRole.ATHLETE, UserRole.COACH]


class UserIdInput(BaseModel):
    user_id: int = Field(gt=0)


class RoleChangeInput(UserIdInput):
    role: UserRole


class StatusChangeInput(UserIdInput):
    is_active: bool
