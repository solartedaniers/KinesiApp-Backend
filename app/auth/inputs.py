from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.core.input_rules import InputModel, parse_input, rules_of
from app.identity.password_policy import PasswordPolicy
from app.models.user import UserRole
from app.identity.person_name import PersonName


@dataclass(frozen=True)
class AuthInputRules:
    """Agrupo las reglas de las peticiones de autenticación que salen de la configuración."""

    password_policy: PasswordPolicy
    otp_length: int

    def parse(self, model: type[InputModel], data: dict[str, Any]) -> InputModel:
        return parse_input(model, data, self)


def _rules(info: ValidationInfo) -> AuthInputRules:
    return rules_of(info, AuthInputRules)


def _strong_password(value: str, info: ValidationInfo) -> str:
    return _rules(info).password_policy.ensure_valid(value)


def _existing_password(value: str, info: ValidationInfo) -> str:
    # No aplico la política vigente: una contraseña anterior a la regla debe seguir sirviendo para entrar
    if not 1 <= len(value) <= _rules(info).password_policy.max_length:
        raise ValueError("Password is required")
    return value


class EmailInput(BaseModel):
    email: EmailStr


class CodeInput(EmailInput):
    code: str

    @field_validator("code")
    @classmethod
    def _code_format(cls, value: str, info: ValidationInfo) -> str:
        length = _rules(info).otp_length
        if len(value) != length or not (value.isascii() and value.isdigit()):
            raise ValueError(f"Code must have {length} digits")
        return value


class RegisterInput(EmailInput):
    password: str
    full_name: PersonName
    # En el registro público solo admito estos dos; ADMIN lo asigna otro admin
    role: Literal[UserRole.ATHLETE, UserRole.COACH]
    accepted_video_consent_version: int

    _password = field_validator("password")(_strong_password)


class LoginInput(EmailInput):
    password: str

    _password = field_validator("password")(_existing_password)


class RefreshTokenInput(BaseModel):
    refresh_token: str = Field(min_length=1)


class PasswordResetInput(CodeInput):
    new_password: str

    _new_password = field_validator("new_password")(_strong_password)


class PasswordChangeInput(BaseModel):
    current_password: str
    new_password: str

    _current_password = field_validator("current_password")(_existing_password)
    _new_password = field_validator("new_password")(_strong_password)
