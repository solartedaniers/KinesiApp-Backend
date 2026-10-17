"""Servidor gRPC en un puerto libre de localhost para probar servicers e interceptores por la red."""

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager

import grpc
from google.rpc import error_details_pb2
from grpc_status import rpc_status


@asynccontextmanager
async def serving(
    register: Callable[[grpc.aio.Server], None], interceptors: Sequence[grpc.aio.ServerInterceptor] = ()
) -> AsyncIterator[grpc.aio.Channel]:
    server = grpc.aio.server(interceptors=list(interceptors))
    register(server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            yield channel
    finally:
        await server.stop(None)


def error_info(error: grpc.aio.AioRpcError) -> error_details_pb2.ErrorInfo:
    info = error_details_pb2.ErrorInfo()
    status = rpc_status.from_call(error)
    assert status is not None, "the error has no google.rpc.Status details"
    assert any(detail.Unpack(info) for detail in status.details)
    return info
