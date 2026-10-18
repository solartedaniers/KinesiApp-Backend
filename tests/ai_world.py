"""Levanto una IA falsa por gRPC y, delante, un puente gRPC-Web como el Envoy de la IA real.

Así pruebo los dos transportes por la red contra el mismo servidor.
"""

import asyncio
import base64
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import quote

import grpc
from google.protobuf import any_pb2
from google.rpc import error_details_pb2, status_pb2
from grpc_status import rpc_status

AI_TOKEN = "test-ai-service-token-with-32-characters"
_FRAME_HEADER_SIZE = 5


async def abort_with_reason(context: grpc.aio.ServicerContext, code: grpc.StatusCode, reason: str) -> None:
    """Respondo como la IA real: el status con un google.rpc.ErrorInfo en los detalles."""
    detail = any_pb2.Any()
    detail.Pack(error_details_pb2.ErrorInfo(reason=reason, domain="ai.kinesiapp"))
    status = rpc_status.to_status(status_pb2.Status(code=code.value[0], message=reason, details=[detail]))
    await context.abort(status.code, status.details, status.trailing_metadata)


async def require_token(context: grpc.aio.ServicerContext) -> None:
    metadata = dict(context.invocation_metadata() or ())
    if metadata.get("authorization") != f"Bearer {AI_TOKEN}":
        await abort_with_reason(context, grpc.StatusCode.UNAUTHENTICATED, "UNAUTHORIZED")


@dataclass(frozen=True)
class AiEndpoints:
    grpc_target: str
    grpc_web_url: str


@asynccontextmanager
async def ai_world(registrations: Sequence[Callable[[grpc.aio.Server], None]]) -> AsyncIterator[AiEndpoints]:
    server = grpc.aio.server()
    for register in registrations:
        register(server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    bridge = await asyncio.start_server(lambda reader, writer: _bridge(channel, reader, writer), "127.0.0.1", 0)
    bridge_port = bridge.sockets[0].getsockname()[1]
    try:
        yield AiEndpoints(f"127.0.0.1:{port}", f"http://127.0.0.1:{bridge_port}")
    finally:
        bridge.close()
        await channel.close()
        await server.stop(None)


async def _bridge(channel: grpc.aio.Channel, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            head = (await reader.readuntil(b"\r\n\r\n")).decode()
            request_line, *lines = head.strip().split("\r\n")
            path = request_line.split(" ")[1]
            headers = {key.strip().lower(): value.strip() for key, _, value in (line.partition(":") for line in lines)}
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            await _relay(channel, path, headers, body[_FRAME_HEADER_SIZE:], writer)
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()


async def _relay(channel: grpc.aio.Channel, path: str, headers: dict[str, str], payload: bytes, writer) -> None:
    metadata = [("authorization", headers["authorization"])] if "authorization" in headers else []
    timeout = int(headers["grpc-timeout"].removesuffix("m")) / 1000 if "grpc-timeout" in headers else None
    writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/grpc-web+proto\r\ntransfer-encoding: chunked\r\n\r\n")
    trailers = {"grpc-status": "0"}
    try:
        async for message in channel.unary_stream(path)(payload, metadata=metadata, timeout=timeout):
            await _chunk(writer, _frame(0, message))
    except grpc.aio.AioRpcError as error:
        trailers = {"grpc-status": str(error.code().value[0]), "grpc-message": quote(error.details() or "")}
        for key, value in error.trailing_metadata() or ():
            if key == "grpc-status-details-bin":
                trailers[key] = base64.b64encode(value).decode().rstrip("=")
    await _chunk(writer, _frame(0x80, "".join(f"{key}: {value}\r\n" for key, value in trailers.items()).encode()))
    writer.write(b"0\r\n\r\n")
    await writer.drain()


def _frame(flag: int, payload: bytes) -> bytes:
    return bytes([flag]) + len(payload).to_bytes(4, "big") + payload


async def _chunk(writer: asyncio.StreamWriter, data: bytes) -> None:
    writer.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
    await writer.drain()
