from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from app.settings.ai import AiClientSettings
from app.settings.base import ENV_FILE, EnvSettings


class AnalysisSettings(EnvSettings):
    """Configuro cómo proceso los análisis en segundo plano con las variables ANALYSIS_*.

    Los valores salen de medir la IA en Azure Container Apps (1 vCPU): ~35 s de arranque en frío desde
    Render y ~40 s para un video de 40 s.
    """

    model_config = SettingsConfigDict(env_prefix="ANALYSIS_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Le doy a cada llamada a AnalyzeVideo, ya con la IA despierta por WarmUp, un plazo que cubre con holgura un
    # video de 40 s y queda bajo los 240 s con que el ingress de Azure corta una solicitud
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
    # Mientras el lease de un intento no vence, ninguna otra instancia lo reclama. El intento lo renueva cada vez
    # que guarda progreso, así que tiene que cubrir lo más largo sin avance: despertar la IA más AnalyzeVideo
    PROCESSING_LEASE_SECONDS: float = Field(default=300.0, gt=0)
    # Cada cuánto busco análisis con el lease vencido, además de al arrancar
    RECOVERY_INTERVAL_SECONDS: float = Field(default=60.0, gt=0)

    @model_validator(mode="after")
    def _ceiling_covers_first_delay(self) -> "AnalysisSettings":
        if self.RETRY_MAX_DELAY_SECONDS < self.RETRY_INITIAL_DELAY_SECONDS:
            raise ValueError("ANALYSIS_RETRY_MAX_DELAY_SECONDS must not be below ANALYSIS_RETRY_INITIAL_DELAY_SECONDS")
        return self


def ensure_lease_outlasts_ai_call(analysis: AnalysisSettings, ai: AiClientSettings) -> None:
    # Lo valido al arrancar porque un lease más corto que la llamada deja que otra instancia duplique el análisis
    longest_call = ai.WAKE_UP_TIMEOUT_SECONDS + analysis.STREAM_TIMEOUT_SECONDS
    if analysis.PROCESSING_LEASE_SECONDS <= longest_call:
        raise ValueError(
            "ANALYSIS_PROCESSING_LEASE_SECONDS must exceed AI_WAKE_UP_TIMEOUT_SECONDS + ANALYSIS_STREAM_TIMEOUT_SECONDS"
            f" ({longest_call:g} s)"
        )
