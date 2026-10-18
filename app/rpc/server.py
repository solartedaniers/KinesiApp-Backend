"""Arranco el servidor gRPC asíncrono con python -m app.rpc.server (con generated/ en PYTHONPATH)."""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Sequence

import grpc

from app.core.async_database import build_async_engine, build_session_factory
from app.identity.access_tokens import AccessTokenVerifier, JwtAccessTokenVerifier
from app.rpc.interceptors.auth import AuthInterceptor
from app.rpc.interceptors.errors import ErrorInterceptor
from app.rpc.interceptors.logging import LoggingInterceptor
from app.rpc.service_factory import RpcServiceFactory, ServicerRegistration
from app.settings.auth import AuthSettings
from app.settings.database import DatabaseSettings
from app.settings.grpc import GrpcServerSettings

logger = logging.getLogger(__name__)


def build_interceptors(verifier: AccessTokenVerifier) -> list[grpc.aio.ServerInterceptor]:
    # Pongo logging primero para que vea el status final, y errores antes de auth para traducir sus rechazos
    return [LoggingInterceptor(), ErrorInterceptor(), AuthInterceptor(verifier)]


def build_server(
    settings: GrpcServerSettings,
    interceptors: Sequence[grpc.aio.ServerInterceptor],
    registrations: Sequence[ServicerRegistration],
) -> grpc.aio.Server:
    server = grpc.aio.server(interceptors=list(interceptors))
    for register in registrations:
        register(server)
    server.add_insecure_port(f"{settings.HOST}:{settings.PORT}")
    return server


async def serve(settings: GrpcServerSettings, auth_settings: AuthSettings, database_settings: DatabaseSettings) -> None:
    engine = build_async_engine(database_settings)
    session_factory = build_session_factory(engine)
    verifier = JwtAccessTokenVerifier(auth_settings, session_factory)
    factory = RpcServiceFactory(session_factory, auth_settings)
    server = build_server(settings, build_interceptors(verifier), factory.registrations())
    await server.start()
    logger.info("gRPC server listening on %s:%s", settings.HOST, settings.PORT)

    stopping = asyncio.Event()
    # Escucho SIGTERM porque así detiene Render el contenedor; en Windows no existe y basta Ctrl+C
    with contextlib.suppress(NotImplementedError):
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopping.set)
    try:
        await stopping.wait()
    finally:
        await server.stop(settings.SHUTDOWN_GRACE_SECONDS)
        await factory.aclose()
        await engine.dispose()
        logger.info("gRPC server stopped")


# Estas librerías registran las peticiones con su URL y sus encabezados firmados en DEBUG (httpx ya en
# INFO); las dejo en WARNING para que subir el nivel del log nunca exponga una firma
QUIET_HTTP_LOGGERS = ("botocore", "boto3", "s3transfer", "urllib3", "httpx", "httpcore")


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level)
    for name in QUIET_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


if __name__ == "__main__":
    configure_logging()
    asyncio.run(serve(GrpcServerSettings(), AuthSettings(), DatabaseSettings()))
