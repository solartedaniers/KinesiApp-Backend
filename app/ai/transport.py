from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

import grpc
from google.protobuf.descriptor import MethodDescriptor
from google.protobuf.message import Message

ReplyType = TypeVar("ReplyType", bound=Message)


class AiCallError(Exception):
    """La IA respondió con un status distinto de OK, o no se pudo llegar a ella."""

    def __init__(self, code: grpc.StatusCode, reason: str | None, message: str) -> None:
        super().__init__(f"{code.name} {reason or '-'}: {message}")
        self.code = code
        # El reason de google.rpc.ErrorInfo que manda la IA (por ejemplo "AI_BUSY"); None si no lo mandó
        self.reason = reason
        self.message = message


class AiTransport(Protocol):
    """Frontera hacia el microservicio de IA: los adaptadores tipados no saben si viajo por gRPC-Web o gRPC.

    Pongo el token de servicio en la metadata y traduzco cualquier fallo a AiCallError.
    """

    async def unary(
        self, method: MethodDescriptor, request: Message, reply_type: type[ReplyType], timeout: float
    ) -> ReplyType: ...

    def server_stream(
        self, method: MethodDescriptor, request: Message, reply_type: type[ReplyType], timeout: float
    ) -> AsyncIterator[ReplyType]: ...

    async def aclose(self) -> None: ...


def rpc_path(method: MethodDescriptor) -> str:
    """Saco la ruta "/paquete.Servicio/Metodo" del descriptor generado, para no escribir nombres a mano."""
    return f"/{method.containing_service.full_name}/{method.name}"


def bearer_metadata(token: str) -> tuple[tuple[str, str], ...]:
    return (("authorization", f"Bearer {token}"),)
