"""Pruebo por la red el adaptador de AnalyzeVideo: el progreso llega como avance y los fallos se clasifican."""

import asyncio

import grpc
import httpx
import pytest
from kinesiapp.ai.v1 import movement_analysis_pb2 as pb, movement_analysis_pb2_grpc
from kinesiapp.common.v1 import movement_pb2

from app.ai.grpc_web_transport import GrpcWebTransport
from app.ai.native_grpc_transport import NativeGrpcTransport
from app.ai.remote_movement_analyzer import AnalyzerError, RemoteMovementAnalyzer
from app.analysis.progress import AnalysisProgressUpdate
from app.models.jump_analysis import AnalysisStage, MovementType
from tests.ai_world import AI_TOKEN, abort_with_reason, ai_world, require_token

RESULT = pb.MovementAnalysisResult(
    risk_assessment=movement_pb2.RiskAssessment(risk_score=0.5), duration_ms=7000, pose_model_version="pose-v1"
)


class _Analysis(movement_analysis_pb2_grpc.MovementAnalysisServiceServicer):
    def __init__(self, fail: tuple[grpc.StatusCode, str | None] | None = None, finish: bool = True) -> None:
        self._fail = fail
        self._finish = finish
        self.requests: list[pb.AnalyzeVideoRequest] = []

    async def AnalyzeVideo(self, request, context):
        await require_token(context)
        self.requests.append(request)
        progress = movement_pb2.AnalysisProgress(
            stage=movement_pb2.ANALYSIS_STAGE_EXTRACTING_POSE, frames_processed=10, frames_total=40
        )
        yield pb.AnalyzeVideoResponse(progress=progress)
        if self._fail:
            code, reason = self._fail
            if reason is None:
                await context.abort(code, "no detail")
            await abort_with_reason(context, code, reason)
        if self._finish:
            yield pb.AnalyzeVideoResponse(result=RESULT)


def _collect(analysis: _Analysis, kind: str = "grpc-web"):
    async def main():
        register = lambda server: movement_analysis_pb2_grpc.add_MovementAnalysisServiceServicer_to_server(analysis, server)
        async with ai_world([register]) as endpoints:
            if kind == "grpc":
                transport = NativeGrpcTransport(grpc.aio.insecure_channel(endpoints.grpc_target), AI_TOKEN)
            else:
                transport = GrpcWebTransport(httpx.AsyncClient(trust_env=False), endpoints.grpc_web_url, AI_TOKEN, 5)
            try:
                analyzer = RemoteMovementAnalyzer(transport, timeout=5)
                return [event async for event in analyzer.analyze("https://bucket.test/v.mp4", MovementType.SQUAT)]
            finally:
                await transport.aclose()

    return asyncio.run(main())


@pytest.mark.parametrize("kind", ["grpc-web", "grpc"])
def test_progress_arrives_as_updates_and_the_stream_ends_with_the_result(kind: str) -> None:
    analysis = _Analysis()

    events = _collect(analysis, kind)

    assert events == [AnalysisProgressUpdate(AnalysisStage.EXTRACTING_POSE, 10, 40), RESULT]
    assert analysis.requests[0].movement_type == movement_pb2.MOVEMENT_TYPE_SQUAT


@pytest.mark.parametrize(
    ("fail", "reason", "retryable"),
    [
        ((grpc.StatusCode.RESOURCE_EXHAUSTED, "AI_BUSY"), "AI_BUSY", True),
        ((grpc.StatusCode.UNAVAILABLE, "STORAGE_UNAVAILABLE"), "STORAGE_UNAVAILABLE", True),
        ((grpc.StatusCode.UNAVAILABLE, None), "AI_UNAVAILABLE", True),
        ((grpc.StatusCode.INVALID_ARGUMENT, "VIDEO_UNREADABLE"), "VIDEO_UNREADABLE", False),
        ((grpc.StatusCode.FAILED_PRECONDITION, "NO_MOVEMENT_DETECTED"), "NO_MOVEMENT_DETECTED", False),
        # Así me llega un RST_STREAM del ingress: INTERNAL sin ErrorInfo, y lo trato como pasajero
        ((grpc.StatusCode.INTERNAL, None), "AI_UNAVAILABLE", True),
    ],
    ids=["busy", "storage", "bare-unavailable", "unreadable", "no-movement", "transport-reset"],
)
def test_failures_keep_their_reason_and_only_passing_ones_are_retryable(fail, reason: str, retryable: bool) -> None:
    with pytest.raises(AnalyzerError) as caught:
        _collect(_Analysis(fail=fail))

    assert (caught.value.reason, caught.value.retryable) == (reason, retryable)


def test_a_stream_without_result_is_a_passing_failure() -> None:
    with pytest.raises(AnalyzerError) as caught:
        _collect(_Analysis(finish=False))

    assert (caught.value.reason, caught.value.retryable) == ("AI_UNAVAILABLE", True)
