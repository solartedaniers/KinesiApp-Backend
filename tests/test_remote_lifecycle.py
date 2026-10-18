"""Pruebo por gRPC-Web cómo despierto a la IA: reintento mientras arranca y me rindo al vencer el plazo."""

import asyncio

import grpc
import httpx
import pytest
from kinesiapp.ai.v1 import lifecycle_pb2, lifecycle_pb2_grpc
from kinesiapp.common.v1 import ai_state_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.grpc_web_transport import GrpcWebTransport
from app.ai.lifecycle import AiState
from app.ai.remote_lifecycle import RemoteAiLifecycle
from app.core.domain_error import DomainError
from tests.ai_world import AI_TOKEN, ai_world, require_token


class _BootingAi(lifecycle_pb2_grpc.AiLifecycleServiceServicer):
    """Responde UNAVAILABLE las primeras veces, como su Envoy mientras grpcio todavía no arranca."""

    def __init__(self, unavailable_calls: int, state=ai_state_pb2.AI_STATE_WARMING_UP) -> None:
        self._unavailable_calls = unavailable_calls
        self._state = state
        self.calls = 0

    async def WarmUp(self, request, context):
        self.calls += 1
        await require_token(context)
        if self.calls <= self._unavailable_calls:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "upstream connect error")
        return lifecycle_pb2.WarmUpResponse(state=self._state)


def _wake_up(ai: _BootingAi, total_timeout: float = 5, token: str = AI_TOKEN):
    async def main():
        register = lambda server: lifecycle_pb2_grpc.add_AiLifecycleServiceServicer_to_server(ai, server)
        async with ai_world([register]) as endpoints:
            transport = GrpcWebTransport(httpx.AsyncClient(trust_env=False), endpoints.grpc_web_url, token, 5)
            try:
                return await RemoteAiLifecycle(transport, total_timeout, call_timeout=2, retry_interval=0.05).wake_up()
            finally:
                await transport.aclose()

    return asyncio.run(main())


def test_a_ready_ai_answers_ready_on_the_first_call() -> None:
    ai = _BootingAi(unavailable_calls=0, state=ai_state_pb2.AI_STATE_READY)

    assert _wake_up(ai) is AiState.READY
    assert ai.calls == 1


def test_while_the_ai_boots_i_retry_until_it_answers() -> None:
    ai = _BootingAi(unavailable_calls=3)

    assert _wake_up(ai) is AiState.WARMING_UP
    assert ai.calls == 4


def test_an_ai_that_never_boots_ends_in_ai_unavailable() -> None:
    with pytest.raises(DomainError) as caught:
        _wake_up(_BootingAi(unavailable_calls=10_000), total_timeout=0.5)

    assert caught.value.reason == ErrorReason.ERROR_REASON_AI_UNAVAILABLE


def test_a_rejected_token_is_not_retried() -> None:
    ai = _BootingAi(unavailable_calls=0)

    with pytest.raises(DomainError) as caught:
        _wake_up(ai, token="x" * 40)

    assert caught.value.reason == ErrorReason.ERROR_REASON_AI_UNAVAILABLE
    assert ai.calls == 1
