import enum
from typing import Protocol

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError


class AiState(str, enum.Enum):
    WARMING_UP = "warming_up"
    READY = "ready"


class AiLifecycle(Protocol):
    """Despierto el servicio de IA; si no responde, lanzo DomainError con AI_UNAVAILABLE."""

    async def wake_up(self) -> AiState: ...


class UnavailableAiLifecycle:
    """La uso mientras la IA no tenga su servicio gRPC desplegado: el frontend muestra que no está disponible."""

    async def wake_up(self) -> AiState:
        raise DomainError(ErrorReason.ERROR_REASON_AI_UNAVAILABLE, "The AI service is not available")
