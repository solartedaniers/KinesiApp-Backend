from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class AthleteProfileBase(BaseModel):
    sport: str = Field(min_length=1, max_length=100)
    height_cm: float = Field(gt=0, le=300)
    weight_kg: float = Field(gt=0, le=400)
    birth_date: date


class AthleteProfileCreate(AthleteProfileBase):
    user_id: int


class AthleteProfileSelfCreate(AthleteProfileBase):
    """Alta del propio perfil: el user_id sale del token (get_current_user), nunca del body."""


class CoachAssignment(BaseModel):
    """Asignación de entrenador a un deportista; sólo un admin puede invocarla."""

    coach_id: int


class AthleteProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    coach_id: int | None
    sport: str
    height_cm: float
    weight_kg: float
    birth_date: date
