from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class AthleteProfileCreate(BaseModel):
    user_id: int
    sport: str = Field(min_length=1, max_length=100)
    height_cm: float = Field(gt=0, le=300)
    weight_kg: float = Field(gt=0, le=400)
    birth_date: date


class AthleteProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    sport: str
    height_cm: float
    weight_kg: float
    birth_date: date
