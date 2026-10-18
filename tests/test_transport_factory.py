"""Pruebo por la red que AI_GRPC_TLS decide si el canal nativo cifra: con TLS no entiende a un servidor sin cifrar."""

import asyncio

import grpc
import pytest
from kinesiapp.ai.v1 import lifecycle_pb2, lifecycle_pb2_grpc
from kinesiapp.common.v1 import ai_state_pb2

from app.ai.transport import AiCallError
from app.ai.transport_factory import build_ai_transport
from app.settings.ai import AiClientSettings
from tests.ai_world import AI_TOKEN, ai_world, require_token

WARM_UP = lifecycle_pb2.DESCRIPTOR.services_by_name["AiLifecycleService"].methods_by_name["WarmUp"]


class _Lifecycle(lifecycle_pb2_grpc.AiLifecycleServiceServicer):
    async def WarmUp(self, request, context):
        await require_token(context)
        return lifecycle_pb2.WarmUpResponse(state=ai_state_pb2.AI_STATE_READY)


def _warm_up(tls: bool):
    async def main():
        register = lambda server: lifecycle_pb2_grpc.add_AiLifecycleServiceServicer_to_server(_Lifecycle(), server)
        async with ai_world([register]) as endpoints:
            settings = AiClientSettings(
                SERVICE_URL=endpoints.grpc_target, SERVICE_TOKEN=AI_TOKEN, TRANSPORT="grpc", GRPC_TLS=tls
            )
            transport = build_ai_transport(settings)
            try:
                return await transport.unary(WARM_UP, lifecycle_pb2.WarmUpRequest(), lifecycle_pb2.WarmUpResponse, 5)
            finally:
                await transport.aclose()

    return asyncio.run(main())


def test_without_tls_the_native_channel_reaches_a_plaintext_server() -> None:
    assert _warm_up(tls=False).state == ai_state_pb2.AI_STATE_READY


def test_with_tls_the_native_channel_refuses_a_plaintext_server() -> None:
    with pytest.raises(AiCallError) as caught:
        _warm_up(tls=True)

    assert caught.value.code is grpc.StatusCode.UNAVAILABLE
