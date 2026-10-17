from collections.abc import Callable
from datetime import datetime

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from kinesiapp.common.v1 import ai_state_pb2
from kinesiapp.system.v1 import system_pb2, system_pb2_grpc

from app.ai.lifecycle import AiLifecycle


class SystemServicer(system_pb2_grpc.SystemServiceServicer):
    """kinesiapp.system.v1.SystemService: transporte, política del cliente y despertar de la IA."""

    def __init__(
        self,
        clock: Callable[[], datetime],
        client_policy: system_pb2.GetClientPolicyResponse,
        ai_lifecycle: AiLifecycle,
    ) -> None:
        self._clock = clock
        self._client_policy = client_policy
        self._ai_lifecycle = ai_lifecycle

    async def Ping(
        self, request: system_pb2.PingRequest, context: grpc.aio.ServicerContext
    ) -> system_pb2.PingResponse:
        server_time = Timestamp()
        server_time.FromDatetime(self._clock())
        return system_pb2.PingResponse(message=request.message, server_time=server_time)

    async def GetClientPolicy(
        self, request: system_pb2.GetClientPolicyRequest, context: grpc.aio.ServicerContext
    ) -> system_pb2.GetClientPolicyResponse:
        return self._client_policy

    async def WakeUpAi(
        self, request: system_pb2.WakeUpAiRequest, context: grpc.aio.ServicerContext
    ) -> system_pb2.WakeUpAiResponse:
        state = await self._ai_lifecycle.wake_up()
        return system_pb2.WakeUpAiResponse(state=ai_state_pb2.AiState.Value(f"AI_STATE_{state.name}"))
