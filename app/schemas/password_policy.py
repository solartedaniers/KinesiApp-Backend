from typing import Annotated

from pydantic import AfterValidator, Field

from app.core.config import settings
from app.identity.password_policy import PasswordPolicy, PasswordRequirement

_policy = PasswordPolicy(settings)
_DESCRIPTIONS = {
    PasswordRequirement.UPPERCASE: "one uppercase letter",
    PasswordRequirement.LOWERCASE: "one lowercase letter",
    PasswordRequirement.DIGIT: "one digit",
    PasswordRequirement.SPECIAL_CHARACTER: "one special character",
}


def _require_character_classes(value: str) -> str:
    missing = _policy.missing_requirements(value)
    if missing:
        raise ValueError(f"Password must contain at least {', '.join(_DESCRIPTIONS[m] for m in missing)}")
    return value


# Política única de contraseñas nuevas (registro, recuperación y cambio): el frontend aplica
# exactamente las mismas reglas en lib/validation.ts (validateNewPassword)
StrongPassword = Annotated[
    str,
    Field(min_length=_policy.min_length, max_length=_policy.max_length),
    AfterValidator(_require_character_classes),
]
