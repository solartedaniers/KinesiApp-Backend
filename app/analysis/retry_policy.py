from dataclasses import dataclass

from app.settings.analysis import AnalysisSettings


@dataclass(frozen=True)
class RetryPolicy:
    """Espera creciente entre intentos: initial, initial·factor, initial·factor²... sin pasar del techo."""

    max_attempts: int
    initial_delay: float
    factor: float
    max_delay: float

    @classmethod
    def from_settings(cls, settings: AnalysisSettings) -> "RetryPolicy":
        return cls(
            settings.MAX_ATTEMPTS,
            settings.RETRY_INITIAL_DELAY_SECONDS,
            settings.RETRY_BACKOFF_FACTOR,
            settings.RETRY_MAX_DELAY_SECONDS,
        )

    def allows(self, attempt: int) -> bool:
        return attempt <= self.max_attempts

    def delay_before(self, attempt: int) -> float:
        # El primer intento sale de inmediato; la espera crece desde el segundo
        if attempt <= 1:
            return 0.0
        return min(self.initial_delay * self.factor ** (attempt - 2), self.max_delay)
