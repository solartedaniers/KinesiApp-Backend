from typing import Annotated

from pydantic import AfterValidator, Field


def _require_letter_and_digit(value: str) -> str:
    if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


# Política única de contraseñas (registro, recuperación y cambio): la app Flutter
# aplica exactamente las mismas reglas en FormValidators.password
StrongPassword = Annotated[
    str, Field(min_length=8, max_length=128), AfterValidator(_require_letter_and_digit)
]
