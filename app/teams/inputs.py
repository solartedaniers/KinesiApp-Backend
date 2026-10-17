from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

TEAM_NAME_MAX_LENGTH = 100  # mismo largo que la columna teams.name

# Quito los espacios de los extremos antes de comparar: "Sub 17 " y "Sub 17" serían el mismo equipo
TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEAM_NAME_MAX_LENGTH)]


class TeamNameInput(BaseModel):
    name: TeamName


class TeamIdInput(BaseModel):
    team_id: int = Field(gt=0)


class TeamRenameInput(TeamIdInput):
    name: TeamName


class TeamMemberInput(TeamIdInput):
    athlete_id: int = Field(gt=0)
