from collections.abc import AsyncIterator

import grpc
from google.protobuf.descriptor import MethodDescriptor
from google.protobuf.message import Message
from grpc_status import rpc_status

from app.ai.status_details import error_reason
from app.ai.transport import AiCallError, ReplyType, bearer_metadata, rpc_path


class NativeGrpcTransport:
    """Adapter: hablo gRPC nativo con grpcio, para cuando la IA quede en la misma red privada que el backend."""

    def __init__(self, channel: grpc.aio.Channel, token: str) -> None:
        self._channel = channel
        self._metadata = bearer_metadata(token)

    async def unary(
        self, method: MethodDescriptor, request: Message, reply_type: type[ReplyType], timeout: float
    ) -> ReplyType:
        call = self._channel.unary_unary(
            rpc_path(method), request_serializer=_serialize, response_deserializer=reply_type.FromString
        )
        try:
            return await call(request, timeout=timeout, metadata=self._metadata)
        except grpc.aio.AioRpcError as error:
            raise _call_error(error) from error

    async def server_stream(
        self, method: MethodDescriptor, request: Message, reply_type: type[ReplyType], timeout: float
    ) -> AsyncIterator[ReplyType]:
        call = self._channel.unary_stream(
            rpc_path(method), request_serializer=_serialize, response_deserializer=reply_type.FromString
        )
        stream = call(request, timeout=timeout, metadata=self._metadata)
        try:
            async for reply in stream:
                yield reply
        except grpc.aio.AioRpcError as error:
            raise _call_error(error) from error
        finally:
            # Si quien consume deja de leer a mitad, cancelo la llamada para que la IA no siga trabajando
            stream.cancel()

    async def aclose(self) -> None:
        await self._channel.close()


def _serialize(message: Message) -> bytes:
    return message.SerializeToString()


def _call_error(error: grpc.aio.AioRpcError) -> AiCallError:
    return AiCallError(error.code(), error_reason(rpc_status.from_call(error)), error.details() or "")
