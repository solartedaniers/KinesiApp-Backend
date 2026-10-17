import asyncio
import logging
from datetime import datetime, timezone

import grpc
import pytest
from kinesiapp.system.v1 import system_pb2, system_pb2_grpc

from app.rpc.interceptors.errors import ErrorInterceptor
from app.rpc.interceptors.logging import LoggingInterceptor
from app.rpc.system_servicer import SystemServicer
from tests.grpc_harness import serving


async def _call_ping_and_wake_up() -> None:
    def register(server: grpc.aio.Server) -> None:
        system_pb2_grpc.add_SystemServiceServicer_to_server(SystemServicer(lambda: datetime.now(timezone.utc)), server)

    async with serving(register, [LoggingInterceptor(), ErrorInterceptor()]) as channel:
        stub = system_pb2_grpc.SystemServiceStub(channel)
        await stub.Ping(system_pb2.PingRequest(message="hola"))
        with pytest.raises(grpc.aio.AioRpcError):
            await stub.WakeUpAi(system_pb2.WakeUpAiRequest())


def test_logs_method_and_final_status_code(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.rpc.interceptors.logging"):
        asyncio.run(_call_ping_and_wake_up())

    lines = [record.getMessage() for record in caplog.records]
    assert lines[0].startswith("/kinesiapp.system.v1.SystemService/Ping OK ")
    assert lines[1].startswith("/kinesiapp.system.v1.SystemService/WakeUpAi UNIMPLEMENTED ")
