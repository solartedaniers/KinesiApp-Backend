from typing import Annotated

from pydantic import AfterValidator, Field

from app.core.config import settings

# Cada requisito con su descripción, en el orden en que se reportan los que faltan
_PASSWORD_REQUIREMENTS = (
    ("one uppercase letter", str.isupper),
    ("one lowercase letter", str.islower),
    ("one digit", str.isdecimal),
    ("one special character", lambda char: not char.isalnum() and not char.isspace()),
)


def _require_character_classes(value: str) -> str:
    missing = [name for name, matches in _PASSWORD_REQUIREMENTS if not any(matches(char) for char in value)]
    if missing:
        raise ValueError(f"Password must contain at least {', '.join(missing)}")
    return value


# Política única de contraseñas nuevas (registro, recuperación y cambio): el frontend aplica
# exactamente las mismas reglas en lib/validation.ts (validateNewPassword)
StrongPassword = Annotated[
    str,
    Field(min_length=settings.PASSWORD_MIN_LENGTH, max_length=settings.PASSWORD_MAX_LENGTH),
    AfterValidator(_require_character_classes),
]
