from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from app.settings.base import ENV_FILE, EnvSettings


class AnalysisSettings(EnvSettings):
    """Configuro cómo proceso los análisis en segundo plano con las variables ANALYSIS_*.

    Los valores salen de medir la IA en Azure Container Apps (1 vCPU): ~35 s de arranque en frío desde
    Render y ~40 s para un video de 40 s.
    """

    model_config = SettingsConfigDict(env_prefix="ANALYSIS_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Plazo de cada llamada a AnalyzeVideo, ya con la IA despierta por WarmUp: cubre el análisis de un video de
    # 40 s con holgura y queda bajo los 240 s con que el ingress de Azure corta una solicitud
    STREAM_TIMEOUT_SECONDS: float = Field(default=180.0, gt=0)
    # Intentos en total por análisis, contando el primero
    MAX_ATTEMPTS: int = Field(default=4, ge=1)
    # Espera creciente entre intentos ante AI_BUSY o UNAVAILABLE: inicial, factor y techo
    RETRY_INITIAL_DELAY_SECONDS: float = Field(default=5.0, ge=0)
    RETRY_BACKOFF_FACTOR: float = Field(default=2.0, ge=1)
    RETRY_MAX_DELAY_SECONDS: float = Field(default=60.0, ge=0)
    # La IA corre un análisis a la vez; si mando más, solo consigo AI_BUSY
    MAX_CONCURRENCY: int = Field(default=1, ge=1)
    # Cada cuánto escribo el progreso en la base; en vivo lo publico siempre
    PROGRESS_PERSIST_INTERVAL_SECONDS: float = Field(default=2.0, ge=0)
    # Al arrancar retomo los PENDING sin progreso desde hace este tiempo: quedaron colgados por un reinicio
    STALE_AFTER_SECONDS: float = Field(default=120.0, gt=0)

    @model_validator(mode="after")
    def _ceiling_covers_first_delay(self) -> "AnalysisSettings":
        if self.RETRY_MAX_DELAY_SECONDS < self.RETRY_INITIAL_DELAY_SECONDS:
            raise ValueError("ANALYSIS_RETRY_MAX_DELAY_SECONDS must not be below ANALYSIS_RETRY_INITIAL_DELAY_SECONDS")
        return self
