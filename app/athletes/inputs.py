from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.core.input_rules import InputModel, parse_input, rules_of
from app.core.time_utils import age_on
from app.models.athlete import Gender
from app.schemas.person_name import PersonName
from app.settings.athlete import AthleteSettings


@dataclass(frozen=True)
class AthleteInputRules:
    min_age_years: int
    max_age_years: int

    @classmethod
    def from_settings(cls, settings: AthleteSettings) -> "AthleteInputRules":
        return cls(settings.ATHLETE_MIN_AGE_YEARS, settings.ATHLETE_MAX_AGE_YEARS)

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


class BiometricsInput(BaseModel):
    gender: Gender
    height_cm: float = Field(gt=0, le=300)
    weight_kg: float = Field(gt=0, le=400)
    birth_date: date

    _birth_date = field_validator("birth_date")(_plausible_birth_date)


class BiometricsUpdateInput(BaseModel):
    gender: Gender | None = None
    height_cm: float | None = Field(default=None, gt=0, le=300)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    birth_date: date | None = None

    _birth_date = field_validator("birth_date")(_plausible_birth_date)

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
