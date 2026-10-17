from collections.abc import Callable
from datetime import datetime

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from kinesiapp.system.v1 import system_pb2, system_pb2_grpc


class SystemServicer(system_pb2_grpc.SystemServiceServicer):
    """kinesiapp.system.v1.SystemService: comprobaciones técnicas del transporte."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def Ping(
        self, request: system_pb2.PingRequest, context: grpc.aio.ServicerContext
    ) -> system_pb2.PingResponse:
        server_time = Timestamp()
        server_time.FromDatetime(self._clock())
        return system_pb2.PingResponse(message=request.message, server_time=server_time)
