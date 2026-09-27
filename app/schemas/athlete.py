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


class AthleteProfileUpdate(BaseModel):
    """Edición parcial de la ficha física: solo se aplican los campos enviados."""

    sport: str | None = Field(default=None, min_length=1, max_length=100)
    height_cm: float | None = Field(default=None, gt=0, le=300)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    birth_date: date | None = None

    def changes(self) -> dict:
        # exclude_none: un null explícito no borra columnas obligatorias, se ignora
        return self.model_dump(exclude_unset=True, exclude_none=True)


class ManagedAthleteCreate(AthleteProfileBase):
    """Deportista sin cuenta propia, creado y gestionado por un coach."""

    full_name: str = Field(min_length=1, max_length=150)


class ManagedAthleteUpdate(AthleteProfileUpdate):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)


class CoachAssignment(BaseModel):
    """Asignación de entrenador a un deportista; sólo un admin puede invocarla."""

    coach_id: int


class AthleteProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    coach_id: int | None
    display_name: str
    is_managed: bool
    sport: str
    height_cm: float
    weight_kg: float
    birth_date: date
