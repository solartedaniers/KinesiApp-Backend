"""Pruebo por la red los dos transportes hacia la IA, gRPC-Web y gRPC nativo, contra la misma IA falsa."""

import asyncio

import grpc
import httpx
import pytest
from kinesiapp.ai.v1 import lifecycle_pb2, lifecycle_pb2_grpc, movement_analysis_pb2, movement_analysis_pb2_grpc
from kinesiapp.common.v1 import ai_state_pb2, movement_pb2

from app.ai.grpc_web_transport import GrpcWebTransport
from app.ai.native_grpc_transport import NativeGrpcTransport
from app.ai.transport import AiCallError, AiTransport
from tests.ai_world import AI_TOKEN, AiEndpoints, abort_with_reason, ai_world, require_token

WARM_UP = lifecycle_pb2.DESCRIPTOR.services_by_name["AiLifecycleService"].methods_by_name["WarmUp"]
ANALYZE = movement_analysis_pb2.DESCRIPTOR.services_by_name["MovementAnalysisService"].methods_by_name["AnalyzeVideo"]
TRANSPORTS = ["grpc-web", "grpc"]


class _Lifecycle(lifecycle_pb2_grpc.AiLifecycleServiceServicer):
    async def WarmUp(self, request, context):
        await require_token(context)
        return lifecycle_pb2.WarmUpResponse(state=ai_state_pb2.AI_STATE_READY)


class _Analysis(movement_analysis_pb2_grpc.MovementAnalysisServiceServicer):
    def __init__(self, fail_after: int | None = None, delay: float = 0.0) -> None:
        self._fail_after = fail_after
        self._delay = delay

    async def AnalyzeVideo(self, request, context):
        await require_token(context)
        for index, stage in enumerate((movement_pb2.ANALYSIS_STAGE_QUEUED, movement_pb2.ANALYSIS_STAGE_DOWNLOADING_VIDEO)):
            if self._fail_after == index:
                await abort_with_reason(context, grpc.StatusCode.RESOURCE_EXHAUSTED, "AI_BUSY")
            await asyncio.sleep(self._delay)
            yield movement_analysis_pb2.AnalyzeVideoResponse(progress=movement_pb2.AnalysisProgress(stage=stage))


def _registrations(analysis: _Analysis):
    return [
        lambda server: lifecycle_pb2_grpc.add_AiLifecycleServiceServicer_to_server(_Lifecycle(), server),
        lambda server: movement_analysis_pb2_grpc.add_MovementAnalysisServiceServicer_to_server(analysis, server),
    ]


def _transport(kind: str, endpoints: AiEndpoints, token: str = AI_TOKEN) -> AiTransport:
    if kind == "grpc":
        return NativeGrpcTransport(grpc.aio.insecure_channel(endpoints.grpc_target), token)
    return GrpcWebTransport(httpx.AsyncClient(trust_env=False), endpoints.grpc_web_url, token, connect_timeout=5)


def _run(kind: str, call, analysis: _Analysis | None = None, token: str = AI_TOKEN):
    async def main():
        async with ai_world(_registrations(analysis or _Analysis())) as endpoints:
            transport = _transport(kind, endpoints, token)
            try:
                return await call(transport)
            finally:
                await transport.aclose()

    return asyncio.run(main())


async def _stages(transport: AiTransport, timeout: float = 5) -> list[int]:
    request = movement_analysis_pb2.AnalyzeVideoRequest(video_url="https://storage.test/v.mp4")
    return [
        reply.progress.stage
        async for reply in transport.server_stream(ANALYZE, request, movement_analysis_pb2.AnalyzeVideoResponse, timeout)
    ]


@pytest.mark.parametrize("kind", TRANSPORTS)
def test_a_unary_call_carries_the_token_and_returns_the_reply(kind: str) -> None:
    reply = _run(kind, lambda t: t.unary(WARM_UP, lifecycle_pb2.WarmUpRequest(), lifecycle_pb2.WarmUpResponse, 5))

    assert reply.state == ai_state_pb2.AI_STATE_READY


@pytest.mark.parametrize("kind", TRANSPORTS)
def test_a_server_stream_arrives_message_by_message(kind: str) -> None:
    stages = _run(kind, _stages)

    assert stages == [movement_pb2.ANALYSIS_STAGE_QUEUED, movement_pb2.ANALYSIS_STAGE_DOWNLOADING_VIDEO]


@pytest.mark.parametrize("kind", TRANSPORTS)
def test_the_reason_of_the_ai_reaches_the_caller(kind: str) -> None:
    async def call(transport):
        with pytest.raises(AiCallError) as caught:
            await _stages(transport)
        return caught.value

    error = _run(kind, call, _Analysis(fail_after=0))

    assert (error.code, error.reason) == (grpc.StatusCode.RESOURCE_EXHAUSTED, "AI_BUSY")


@pytest.mark.parametrize("kind", TRANSPORTS)
def test_an_error_mid_stream_comes_after_the_messages_already_sent(kind: str) -> None:
    received = []

    async def call(transport):
        request = movement_analysis_pb2.AnalyzeVideoRequest()
        with pytest.raises(AiCallError) as caught:
            async for reply in transport.server_stream(ANALYZE, request, movement_analysis_pb2.AnalyzeVideoResponse, 5):
                received.append(reply.progress.stage)
        return caught.value

    error = _run(kind, call, _Analysis(fail_after=1))

    assert received == [movement_pb2.ANALYSIS_STAGE_QUEUED]
    assert error.reason == "AI_BUSY"


@pytest.mark.parametrize("kind", TRANSPORTS)
def test_a_wrong_token_is_unauthenticated(kind: str) -> None:
    async def call(transport):
        with pytest.raises(AiCallError) as caught:
            await transport.unary(WARM_UP, lifecycle_pb2.WarmUpRequest(), lifecycle_pb2.WarmUpResponse, 5)
        return caught.value

    error = _run(kind, call, token="x" * 40)

    assert (error.code, error.reason) == (grpc.StatusCode.UNAUTHENTICATED, "UNAUTHORIZED")


@pytest.mark.parametrize("kind", TRANSPORTS)
def test_a_slow_ai_ends_in_deadline_exceeded(kind: str) -> None:
    async def call(transport):
        with pytest.raises(AiCallError) as caught:
            await _stages(transport, timeout=0.2)
        return caught.value

    error = _run(kind, call, _Analysis(delay=1.0))

    assert error.code is grpc.StatusCode.DEADLINE_EXCEEDED


@pytest.mark.parametrize("kind", TRANSPORTS)
def test_an_unreachable_ai_is_unavailable(kind: str) -> None:
    async def main():
        # Reservo un puerto y lo libero: nadie escucha ahí
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        transport = _transport(kind, AiEndpoints(f"127.0.0.1:{port}", f"http://127.0.0.1:{port}"))
        try:
            with pytest.raises(AiCallError) as caught:
                # Le doy más plazo que lo que tarda Windows en rechazar la conexión
                await transport.unary(WARM_UP, lifecycle_pb2.WarmUpRequest(), lifecycle_pb2.WarmUpResponse, 10)
            return caught.value
        finally:
            await transport.aclose()

    assert asyncio.run(main()).code is grpc.StatusCode.UNAVAILABLE


def test_grpc_web_maps_an_http_error_from_the_proxy_to_a_grpc_status() -> None:
    async def main():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
        transport = GrpcWebTransport(client, "https://ai.test", AI_TOKEN, connect_timeout=2)
        with pytest.raises(AiCallError) as caught:
            await transport.unary(WARM_UP, lifecycle_pb2.WarmUpRequest(), lifecycle_pb2.WarmUpResponse, 2)
        return caught.value

    assert asyncio.run(main()).code is grpc.StatusCode.UNAVAILABLE
