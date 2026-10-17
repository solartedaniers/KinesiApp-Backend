import asyncio
from datetime import datetime, timezone

import grpc
from kinesiapp.system.v1 import system_pb2, system_pb2_grpc

from app.rpc.system_servicer import SystemServicer

FIXED_TIME = datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)


async def _ping_over_the_wire(message: str) -> system_pb2.PingResponse:
    server = grpc.aio.server()
    system_pb2_grpc.add_SystemServiceServicer_to_server(SystemServicer(lambda: FIXED_TIME), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            return await system_pb2_grpc.SystemServiceStub(channel).Ping(system_pb2.PingRequest(message=message))
    finally:
        await server.stop(None)


def test_ping_echoes_the_message_with_the_server_time() -> None:
    response = asyncio.run(_ping_over_the_wire("hola"))

    assert response.message == "hola"
    assert response.server_time.ToDatetime(tzinfo=timezone.utc) == FIXED_TIME
