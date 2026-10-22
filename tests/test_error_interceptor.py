import asyncio

import grpc
import pytest
from google.rpc import error_details_pb2
from grpc_status import rpc_status
from kinesiapp.analysis.v1 import analysis_pb2, analysis_pb2_grpc
from kinesiapp.common.v1 import movement_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from kinesiapp.system.v1 import system_pb2, system_pb2_grpc
from pydantic import BaseModel, ValidationError

from app.core.domain_error import DomainError
from app.rpc.interceptors.errors import ErrorInterceptor
from tests.grpc_harness import error_info, serving


class _Echo(BaseModel):
    message: str


class _FailingSystem(system_pb2_grpc.SystemServiceServicer):
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def Ping(self, request, context):
        raise self._error


class _FailingAnalysis(analysis_pb2_grpc.AnalysisServiceServicer):
    async def WatchAnalysis(self, request, context):
        yield analysis_pb2.WatchAnalysisResponse(progress=movement_pb2.AnalysisProgress(frames_processed=1))
        raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "Analysis not found")


def _validation_error() -> ValidationError:
    try:
        _Echo.model_validate({})
    except ValidationError as error:
        return error
    raise AssertionError("the model accepted an empty payload")


async def _ping(error: Exception) -> grpc.aio.AioRpcError:
    def register(server: grpc.aio.Server) -> None:
        system_pb2_grpc.add_SystemServiceServicer_to_server(_FailingSystem(error), server)

    async with serving(register, [ErrorInterceptor()]) as channel:
        with pytest.raises(grpc.aio.AioRpcError) as raised:
            await system_pb2_grpc.SystemServiceStub(channel).Ping(system_pb2.PingRequest())
    return raised.value


def test_domain_error_becomes_its_status_code_with_error_info() -> None:
    error = asyncio.run(_ping(DomainError(ErrorReason.ERROR_REASON_EMAIL_ALREADY_REGISTERED, "Email taken")))

    assert error.code() == grpc.StatusCode.ALREADY_EXISTS
    assert error.details() == "Email taken"
    info = error_info(error)
    assert (info.reason, info.domain) == ("EMAIL_ALREADY_REGISTERED", "kinesiapp")


def test_validation_error_becomes_invalid_argument_with_field_violations() -> None:
    error = asyncio.run(_ping(_validation_error()))

    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error_info(error).reason == "BAD_REQUEST"
    bad_request = error_details_pb2.BadRequest()
    assert any(detail.Unpack(bad_request) for detail in rpc_status.from_call(error).details)
    assert [v.field for v in bad_request.field_violations] == ["message"]


def test_unexpected_error_becomes_internal_without_leaking_details() -> None:
    error = asyncio.run(_ping(RuntimeError("database password is hunter2")))

    assert error.code() == grpc.StatusCode.INTERNAL
    assert "hunter2" not in (error.details() or "")


def test_domain_error_in_the_middle_of_a_stream_keeps_the_messages_already_sent() -> None:
    async def watch() -> tuple[list[analysis_pb2.WatchAnalysisResponse], grpc.aio.AioRpcError]:
        def register(server: grpc.aio.Server) -> None:
            analysis_pb2_grpc.add_AnalysisServiceServicer_to_server(_FailingAnalysis(), server)

        received = []
        async with serving(register, [ErrorInterceptor()]) as channel:
            with pytest.raises(grpc.aio.AioRpcError) as raised:
                async for response in analysis_pb2_grpc.AnalysisServiceStub(channel).WatchAnalysis(
                    analysis_pb2.WatchAnalysisRequest(analysis_id=1)
                ):
                    received.append(response)
        return received, raised.value

    received, error = asyncio.run(watch())

    assert [r.progress.frames_processed for r in received] == [1]
    assert error.code() == grpc.StatusCode.NOT_FOUND
    assert error_info(error).reason == "NOT_FOUND"


def test_unimplemented_method_still_answers_unimplemented() -> None:
    async def call() -> grpc.aio.AioRpcError:
        def register(server: grpc.aio.Server) -> None:
            system_pb2_grpc.add_SystemServiceServicer_to_server(system_pb2_grpc.SystemServiceServicer(), server)

        async with serving(register, [ErrorInterceptor()]) as channel:
            with pytest.raises(grpc.aio.AioRpcError) as raised:
                await system_pb2_grpc.SystemServiceStub(channel).WakeUpAi(system_pb2.WakeUpAiRequest())
        return raised.value

    assert asyncio.run(call()).code() == grpc.StatusCode.UNIMPLEMENTED
