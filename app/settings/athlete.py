from typing import Self

from pydantic import Field, model_validator

from app.settings.base import EnvSettings


class AthleteSettings(EnvSettings):
    """Fijo los rangos admitidos en la ficha de un deportista: edad, estatura y peso.

    Los mínimos de estatura y peso salen de la edad mínima: un niño de 5 años en el percentil 3 mide
    unos 100 cm y pesa unos 14 kg, así que 80 cm y 15 kg no rechazan a nadie real y sí atrapan una
    estatura escrita en metros. Los máximos dejan margen sobre los deportistas más grandes registrados.
    """

    ATHLETE_MIN_AGE_YEARS: int = Field(default=5, ge=0)
    ATHLETE_MAX_AGE_YEARS: int = Field(default=100, gt=0)
    ATHLETE_MIN_HEIGHT_CM: float = Field(default=80.0, gt=0)
    ATHLETE_MAX_HEIGHT_CM: float = Field(default=250.0, gt=0)
    ATHLETE_MIN_WEIGHT_KG: float = Field(default=15.0, gt=0)
    ATHLETE_MAX_WEIGHT_KG: float = Field(default=250.0, gt=0)

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> Self:
        for low, high in (
            (self.ATHLETE_MIN_AGE_YEARS, self.ATHLETE_MAX_AGE_YEARS),
            (self.ATHLETE_MIN_HEIGHT_CM, self.ATHLETE_MAX_HEIGHT_CM),
            (self.ATHLETE_MIN_WEIGHT_KG, self.ATHLETE_MAX_WEIGHT_KG),
        ):
            if low >= high:
                raise ValueError(f"Athlete range minimum {low} must be lower than its maximum {high}")
        return self
