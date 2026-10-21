from typing import Self

from pydantic import Field, model_validator

from app.settings.base import EnvSettings


class RiskSettings(EnvSettings):
    """Corto el puntaje de riesgo que calcula la IA en niveles. Los umbrales del cálculo viven en la IA."""

    # Cortes de nivel de riesgo: con nivel "high" el chat recomienda consulta profesional
    RISK_LEVEL_MODERATE: float = Field(default=0.33, ge=0, le=1)
    RISK_LEVEL_HIGH: float = Field(default=0.66, ge=0, le=1)

    @model_validator(mode="after")
    def _cuts_are_ordered(self) -> Self:
        if self.RISK_LEVEL_MODERATE >= self.RISK_LEVEL_HIGH:
            raise ValueError("RISK_LEVEL_MODERATE must be lower than RISK_LEVEL_HIGH")
        return self
