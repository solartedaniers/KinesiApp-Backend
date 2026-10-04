from datetime import date
from typing import Annotated

from pydantic import AfterValidator

from app.core.config import settings
from app.core.time_utils import age_on


def _require_plausible_age(value: date) -> date:
    today = date.today()
    if value >= today:
        raise ValueError("Birth date must be in the past")
    age = age_on(value, today)
    if not settings.ATHLETE_MIN_AGE_YEARS <= age <= settings.ATHLETE_MAX_AGE_YEARS:
        raise ValueError(
            f"Age must be between {settings.ATHLETE_MIN_AGE_YEARS} and {settings.ATHLETE_MAX_AGE_YEARS} years"
        )
    return value


# Fecha de nacimiento de un deportista: la edad se calcula a partir de ella y nunca se almacena.
# El frontend aplica el mismo rango en lib/validation.ts (validateBirthDate)
BirthDate = Annotated[date, AfterValidator(_require_plausible_age)]
