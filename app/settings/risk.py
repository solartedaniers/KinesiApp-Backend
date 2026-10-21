from pydantic import Field

from app.settings.base import EnvSettings


class RiskSettings(EnvSettings):
    """Corto el puntaje de riesgo que calcula la IA en niveles. Los umbrales del cálculo viven en la IA."""

    # Cortes de nivel de riesgo: con nivel "high" el chat recomienda consulta profesional
    RISK_LEVEL_MODERATE: float = Field(default=0.33, ge=0, le=1)
    RISK_LEVEL_HIGH: float = Field(default=0.66, ge=0, le=1)
