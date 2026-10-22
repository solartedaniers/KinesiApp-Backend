from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError
from app.identity.access_tokens import AccessTokenVerifier
from app.identity.principal import bind_principal, unbind_principal
from app.rpc.access_policy import access_for
from app.rpc.interceptors.call_scope import CallScopeInterceptor

_BEARER_PREFIX = "bearer "


class AuthInterceptor(CallScopeInterceptor):
    """Aplico la política de acceso del contrato con el token Bearer de la metadata "authorization"."""

    def __init__(self, verifier: AccessTokenVerifier) -> None:
        self._verifier = verifier

    @asynccontextmanager
    async def scope(self, method: str, context: grpc.aio.ServicerContext) -> AsyncIterator[None]:
        access = access_for(method)
        if access.public:
            yield
            return
        principal = await self._verifier.verify(_bearer_token(context))
        if access.roles and principal.role not in access.roles:
            raise DomainError(ErrorReason.ERROR_REASON_FORBIDDEN, "You don't have permission to perform this operation")
        token = bind_principal(principal)
        try:
            yield
        finally:
            unbind_principal(token)


def _bearer_token(context: grpc.aio.ServicerContext) -> str:
    for key, value in context.invocation_metadata() or ():
        if key == "authorization" and isinstance(value, str) and value.lower().startswith(_BEARER_PREFIX):
            return value[len(_BEARER_PREFIX):].strip()
    raise DomainError(ErrorReason.ERROR_REASON_UNAUTHORIZED, "Missing bearer token")
