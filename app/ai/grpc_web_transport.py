import base64
import binascii
import struct
import time
from collections.abc import AsyncIterator
from urllib.parse import unquote

import grpc
import httpx
from google.protobuf.descriptor import MethodDescriptor
from google.protobuf.message import DecodeError, Message
from google.rpc import status_pb2

from app.ai.status_details import error_reason
from app.ai.transport import AiCallError, ReplyType, rpc_path

_CONTENT_TYPE = "application/grpc-web+proto"
_FRAME_HEADER = struct.Struct(">BI")
_TRAILER_FLAG = 0x80
# Cómo traduce gRPC un status HTTP cuando la respuesta no llegó a ser gRPC (doc http-grpc-status-mapping)
_STATUS_BY_HTTP = {
    400: grpc.StatusCode.INTERNAL,
    401: grpc.StatusCode.UNAUTHENTICATED,
    403: grpc.StatusCode.PERMISSION_DENIED,
    404: grpc.StatusCode.UNIMPLEMENTED,
    429: grpc.StatusCode.UNAVAILABLE,
    502: grpc.StatusCode.UNAVAILABLE,
    503: grpc.StatusCode.UNAVAILABLE,
    504: grpc.StatusCode.UNAVAILABLE,
}
_STATUS_BY_VALUE = {status.value[0]: status for status in grpc.StatusCode}


class GrpcWebTransport:
    """Adapter: hablo gRPC-Web sobre HTTP/1.1 con httpx, que es lo que el Envoy de la IA acepta desde internet."""

    def __init__(self, client: httpx.AsyncClient, base_url: str, token: str, connect_timeout: float) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._connect_timeout = connect_timeout

    async def unary(
        self, method: MethodDescriptor, request: Message, reply_type: type[ReplyType], timeout: float
    ) -> ReplyType:
        replies = [reply async for reply in self.server_stream(method, request, reply_type, timeout)]
        if len(replies) != 1:
            raise AiCallError(grpc.StatusCode.INTERNAL, None, f"Expected one reply, got {len(replies)}")
        return replies[0]

    async def server_stream(
        self, method: MethodDescriptor, request: Message, reply_type: type[ReplyType], timeout: float
    ) -> AsyncIterator[ReplyType]:
        deadline = time.monotonic() + timeout
        payload = request.SerializeToString()
        headers = {
            "content-type": _CONTENT_TYPE,
            "x-grpc-web": "1",
            "authorization": f"Bearer {self._token}",
            # Le paso el plazo a la IA para que también ella deje de trabajar cuando ya no espero la respuesta
            "grpc-timeout": f"{max(1, round(timeout * 1000))}m",
        }
        try:
            async with self._client.stream(
                "POST",
                self._base_url + rpc_path(method),
                content=_FRAME_HEADER.pack(0, len(payload)) + payload,
                headers=headers,
                # El read timeout corta si la IA deja de mandar bytes; el plazo total lo controlo yo
                timeout=httpx.Timeout(timeout, connect=self._connect_timeout),
            ) as response:
                if response.status_code != 200:
                    code = _STATUS_BY_HTTP.get(response.status_code, grpc.StatusCode.UNKNOWN)
                    raise AiCallError(code, None, f"HTTP {response.status_code}")
                # Si la IA falla antes de responder nada, el status viene en los headers (trailers-only)
                trailers = {key.lower(): value for key, value in response.headers.items()}
                async for flag, frame in _frames(response.aiter_bytes()):
                    if flag & _TRAILER_FLAG:
                        trailers.update(_parse_trailers(frame))
                        continue
                    yield _decode(reply_type, frame)
                    if time.monotonic() > deadline:
                        raise AiCallError(grpc.StatusCode.DEADLINE_EXCEEDED, None, "Deadline exceeded")
        except httpx.ConnectTimeout as error:
            # No llegué a la IA: lo trato como caída y no como plazo vencido, igual que grpcio
            raise AiCallError(grpc.StatusCode.UNAVAILABLE, None, type(error).__name__) from error
        except httpx.TimeoutException as error:
            raise AiCallError(grpc.StatusCode.DEADLINE_EXCEEDED, None, type(error).__name__) from error
        except httpx.HTTPError as error:
            raise AiCallError(grpc.StatusCode.UNAVAILABLE, None, type(error).__name__) from error
        _raise_for_status(trailers)

    async def aclose(self) -> None:
        await self._client.aclose()


async def _frames(chunks: AsyncIterator[bytes]) -> AsyncIterator[tuple[int, bytes]]:
    buffer = b""
    async for chunk in chunks:
        buffer += chunk
        while len(buffer) >= _FRAME_HEADER.size:
            flag, length = _FRAME_HEADER.unpack_from(buffer)
            end = _FRAME_HEADER.size + length
            if len(buffer) < end:
                break
            yield flag, buffer[_FRAME_HEADER.size : end]
            buffer = buffer[end:]
    if buffer:
        raise AiCallError(grpc.StatusCode.INTERNAL, None, "Truncated gRPC-Web frame")


def _decode(reply_type: type[ReplyType], frame: bytes) -> ReplyType:
    try:
        return reply_type.FromString(frame)
    except DecodeError as error:
        raise AiCallError(grpc.StatusCode.INTERNAL, None, "Undecodable reply") from error


def _parse_trailers(frame: bytes) -> dict[str, str]:
    trailers = {}
    for line in frame.decode("utf-8", errors="replace").split("\r\n"):
        key, separator, value = line.partition(":")
        if separator:
            trailers[key.strip().lower()] = value.strip()
    return trailers


def _raise_for_status(trailers: dict[str, str]) -> None:
    raw_code = trailers.get("grpc-status")
    if raw_code is None:
        raise AiCallError(grpc.StatusCode.INTERNAL, None, "Missing grpc-status")
    code = _STATUS_BY_VALUE.get(int(raw_code), grpc.StatusCode.UNKNOWN) if raw_code.isdigit() else grpc.StatusCode.UNKNOWN
    if code is grpc.StatusCode.OK:
        return
    raise AiCallError(code, error_reason(_status_details(trailers)), unquote(trailers.get("grpc-message", "")))


def _status_details(trailers: dict[str, str]) -> status_pb2.Status | None:
    raw = trailers.get("grpc-status-details-bin")
    if not raw:
        return None
    try:
        # Los headers binarios de gRPC van en base64 sin relleno
        return status_pb2.Status.FromString(base64.b64decode(raw + "=" * (-len(raw) % 4)))
    except (binascii.Error, DecodeError):
        return None
