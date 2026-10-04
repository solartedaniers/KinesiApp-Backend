from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

# Sin espacios en los extremos: "Sub 17 " y "Sub 17" son el mismo equipo
TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class TeamCreate(BaseModel):
    name: TeamName


class TeamUpdate(BaseModel):
    name: TeamName


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_id: int
    athlete_ids: list[int]
    created_at: datetime
