import grpc
import httpx

from app.ai.grpc_web_transport import GrpcWebTransport
from app.ai.native_grpc_transport import NativeGrpcTransport
from app.ai.transport import AiTransport
from app.settings.ai import AiClientSettings


def build_ai_transport(settings: AiClientSettings) -> AiTransport:
    """Factory: elijo el transporte hacia la IA con AI_TRANSPORT, sin que los adaptadores tipados cambien."""
    token = settings.SERVICE_TOKEN.get_secret_value()
    if settings.TRANSPORT == "grpc":
        return NativeGrpcTransport(_channel(settings), token)
    # trust_env=False para que un proxy del entorno nunca vea el token de servicio
    client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
    return GrpcWebTransport(client, settings.SERVICE_URL, token, settings.CONNECT_TIMEOUT_SECONDS)


def _channel(settings: AiClientSettings) -> grpc.aio.Channel:
    if settings.GRPC_TLS:
        return grpc.aio.secure_channel(settings.SERVICE_URL, grpc.ssl_channel_credentials())
    return grpc.aio.insecure_channel(settings.SERVICE_URL)
