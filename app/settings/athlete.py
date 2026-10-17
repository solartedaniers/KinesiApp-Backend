from pydantic import Field

from app.settings.base import EnvSettings


class AthleteSettings(EnvSettings):
    """Fijo el rango de edad admitido en la ficha de un deportista (app/schemas/birth_date.py)."""

    ATHLETE_MIN_AGE_YEARS: int = Field(default=5, ge=0)
    ATHLETE_MAX_AGE_YEARS: int = Field(default=100, gt=0)
