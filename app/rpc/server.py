"""Servidor gRPC asíncrono del backend. Uso: python -m app.rpc.server (con generated/ en PYTHONPATH)."""

import asyncio
import contextlib
import logging
import signal
from datetime import datetime, timezone

import grpc
from kinesiapp.system.v1 import system_pb2_grpc

from app.rpc.system_servicer import SystemServicer
from app.settings.grpc import GrpcServerSettings

logger = logging.getLogger(__name__)


def build_server(settings: GrpcServerSettings) -> grpc.aio.Server:
    server = grpc.aio.server()
    system_pb2_grpc.add_SystemServiceServicer_to_server(SystemServicer(lambda: datetime.now(timezone.utc)), server)
    server.add_insecure_port(f"{settings.HOST}:{settings.PORT}")
    return server


async def serve(settings: GrpcServerSettings) -> None:
    server = build_server(settings)
    await server.start()
    logger.info("gRPC server listening on %s:%s", settings.HOST, settings.PORT)

    stopping = asyncio.Event()
    # Render detiene el contenedor con SIGTERM; en Windows no existe add_signal_handler y basta Ctrl+C
    with contextlib.suppress(NotImplementedError):
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopping.set)
    try:
        await stopping.wait()
    finally:
        await server.stop(settings.SHUTDOWN_GRACE_SECONDS)
        logger.info("gRPC server stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(GrpcServerSettings()))
