import enum
from typing import Protocol


class AiState(str, enum.Enum):
    WARMING_UP = "warming_up"
    READY = "ready"


class AiLifecycle(Protocol):
    """Despierto el servicio de IA; si no responde, lanzo DomainError con AI_UNAVAILABLE."""

    async def wake_up(self) -> AiState: ...
