import enum
from collections.abc import Callable

from app.settings.auth import PasswordPolicySettings


class PasswordRequirement(str, enum.Enum):
    """Clases de caracter exigidas; mismos nombres que kinesiapp.system.v1.PasswordRequirement."""

    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"
    DIGIT = "digit"
    SPECIAL_CHARACTER = "special_character"


# En el orden en que se informan las que faltan
_MATCHERS: dict[PasswordRequirement, Callable[[str], bool]] = {
    PasswordRequirement.UPPERCASE: str.isupper,
    PasswordRequirement.LOWERCASE: str.islower,
    PasswordRequirement.DIGIT: str.isdecimal,
    PasswordRequirement.SPECIAL_CHARACTER: lambda char: not char.isalnum() and not char.isspace(),
}


class PasswordPolicy:
    """Política única de contraseñas nuevas (registro, recuperación y cambio)."""

    requirements: tuple[PasswordRequirement, ...] = tuple(_MATCHERS)

    def __init__(self, settings: PasswordPolicySettings) -> None:
        self.min_length = settings.PASSWORD_MIN_LENGTH
        self.max_length = settings.PASSWORD_MAX_LENGTH

    def missing_requirements(self, password: str) -> list[PasswordRequirement]:
        return [requirement for requirement, matches in _MATCHERS.items() if not any(map(matches, password))]
