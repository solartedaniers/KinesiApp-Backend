import unicodedata
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field

FULL_NAME_MAX_LENGTH = 150  # mismo largo que las columnas full_name


def _normalize(value: object) -> object:
    # NFC: algunos teclados mandan "é" como "e" + tilde combinable, que no cuenta como letra.
    # Los espacios sobrantes se colapsan en vez de rechazar el nombre
    if not isinstance(value, str):
        return value
    return " ".join(unicodedata.normalize("NFC", value).split())


def _require_letters_only(value: str) -> str:
    if not all(word.isalpha() for word in value.split(" ")):
        raise ValueError("Full name may only contain letters and spaces")
    return value


# Nombre de una persona: sólo letras (con tildes, ñ, etc.) y un espacio entre palabras. El
# frontend aplica la misma regla en lib/validation.ts (validateFullName)
PersonName = Annotated[
    str,
    BeforeValidator(_normalize),
    Field(min_length=1, max_length=FULL_NAME_MAX_LENGTH),
    AfterValidator(_require_letters_only),
]
