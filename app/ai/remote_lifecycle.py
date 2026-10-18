import asyncio
import logging
import time

import grpc
from kinesiapp.ai.v1 import lifecycle_pb2
from kinesiapp.common.v1 import ai_state_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.lifecycle import AiState
from app.ai.transport import AiCallError, AiTransport
from app.core.domain_error import DomainError

logger = logging.getLogger(__name__)

_WARM_UP = lifecycle_pb2.DESCRIPTOR.services_by_name["AiLifecycleService"].methods_by_name["WarmUp"]
_STATE_BY_PROTO = {
    ai_state_pb2.AI_STATE_WARMING_UP: AiState.WARMING_UP,
    ai_state_pb2.AI_STATE_READY: AiState.READY,
}


class RemoteAiLifecycle:
    """Adapter de AiLifecycle sobre el WarmUp de la IA.

    Mientras el contenedor despierta, su Envoy responde UNAVAILABLE: reintento hasta el plazo total y
    devuelvo el estado en cuanto la IA conteste, para que el frontend muestre "IA despertando".
    """

    def __init__(
        self, transport: AiTransport, total_timeout: float, call_timeout: float, retry_interval: float
    ) -> None:
        self._transport = transport
        self._total_timeout = total_timeout
        self._call_timeout = call_timeout
        self._retry_interval = retry_interval

    async def wake_up(self) -> AiState:
        deadline = time.monotonic() + self._total_timeout
        while True:
            remaining = deadline - time.monotonic()
            try:
                reply = await self._transport.unary(
                    _WARM_UP, lifecycle_pb2.WarmUpRequest(), lifecycle_pb2.WarmUpResponse, min(self._call_timeout, remaining)
                )
            except AiCallError as error:
                retryable = error.code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
                # Mido de nuevo porque el intento pudo gastar casi todo el plazo
                if not retryable or deadline - time.monotonic() <= self._retry_interval:
                    logger.warning("AI did not wake up: %s", error)
                    raise _unavailable() from error
                await asyncio.sleep(self._retry_interval)
                continue
            state = _STATE_BY_PROTO.get(reply.state)
            if state is None:
                raise _unavailable()
            return state


def _unavailable() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_AI_UNAVAILABLE, "The AI service is not available")
