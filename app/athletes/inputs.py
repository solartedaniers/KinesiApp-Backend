from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.core.input_rules import InputModel, parse_input, rules_of
from app.core.time_utils import age_on
from app.models.athlete import Gender
from app.identity.person_name import PersonName
from app.settings.athlete import AthleteSettings


@dataclass(frozen=True)
class AthleteInputRules:
    min_age_years: int
    max_age_years: int
    min_height_cm: float
    max_height_cm: float
    min_weight_kg: float
    max_weight_kg: float

    @classmethod
    def from_settings(cls, settings: AthleteSettings) -> "AthleteInputRules":
        return cls(
            settings.ATHLETE_MIN_AGE_YEARS,
            settings.ATHLETE_MAX_AGE_YEARS,
            settings.ATHLETE_MIN_HEIGHT_CM,
            settings.ATHLETE_MAX_HEIGHT_CM,
            settings.ATHLETE_MIN_WEIGHT_KG,
            settings.ATHLETE_MAX_WEIGHT_KG,
        )

    def parse(self, model: type[InputModel], data: dict[str, Any]) -> InputModel:
        return parse_input(model, data, self)


def _plausible_birth_date(value: date | None, info: ValidationInfo) -> date | None:
    if value is None:
        return None
    today = date.today()
    if value >= today:
        raise ValueError("Birth date must be in the past")
    rules = rules_of(info, AthleteInputRules)
    if not rules.min_age_years <= age_on(value, today) <= rules.max_age_years:
        raise ValueError(f"Age must be between {rules.min_age_years} and {rules.max_age_years} years")
    return value


def _realistic_measure(value: float | None, info: ValidationInfo) -> float | None:
    if value is None:
        return None
    rules = rules_of(info, AthleteInputRules)
    low, high = (
        (rules.min_height_cm, rules.max_height_cm) if info.field_name == "height_cm" else (rules.min_weight_kg, rules.max_weight_kg)
    )
    if not low <= value <= high:
        raise ValueError(f"{info.field_name} must be between {low:g} and {high:g}")
    return value


class BiometricsInput(BaseModel):
    gender: Gender
    height_cm: float
    weight_kg: float
    birth_date: date

    _birth_date = field_validator("birth_date")(_plausible_birth_date)
    _measures = field_validator("height_cm", "weight_kg")(_realistic_measure)


class BiometricsUpdateInput(BaseModel):
    gender: Gender | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    birth_date: date | None = None

    _birth_date = field_validator("birth_date")(_plausible_birth_date)
    _measures = field_validator("height_cm", "weight_kg")(_realistic_measure)

    def changes(self) -> dict[str, Any]:
        # Solo aplico lo que llegó: un campo ausente no borra una columna obligatoria
        return self.model_dump(exclude_unset=True, exclude_none=True)


class AthleteIdInput(BaseModel):
    athlete_id: int = Field(gt=0)


class ProfileForUserInput(BaseModel):
    user_id: int = Field(gt=0)
    biometrics: BiometricsInput


class CoachAssignmentInput(AthleteIdInput):
    coach_id: int = Field(gt=0)


class ManagedAthleteInput(BaseModel):
    full_name: PersonName
    biometrics: BiometricsInput


class ManagedAthleteUpdateInput(AthleteIdInput):
    full_name: PersonName | None = None
    biometrics: BiometricsUpdateInput

    def changes(self) -> dict[str, Any]:
        changes = self.biometrics.changes()
        if self.full_name is not None:
            changes["full_name"] = self.full_name
        return changes
