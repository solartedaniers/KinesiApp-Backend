import asyncio
from datetime import datetime, timezone

import grpc
import pytest
from kinesiapp.admin.v1 import user_admin_pb2, user_admin_pb2_grpc
from kinesiapp.analysis.v1 import analysis_pb2, analysis_pb2_grpc
from kinesiapp.common.v1 import movement_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from kinesiapp.system.v1 import system_pb2, system_pb2_grpc
from kinesiapp.system.v1.system_pb2 import GetClientPolicyResponse

from app.core.domain_error import DomainError
from app.identity.principal import Principal, current_principal
from app.models.user import UserRole
from app.rpc.access_policy import access_for
from app.rpc.interceptors.auth import AuthInterceptor
from app.rpc.interceptors.errors import ErrorInterceptor
from app.ai.lifecycle import UnavailableAiLifecycle
from app.rpc.system_servicer import SystemServicer
from tests.grpc_harness import error_info, serving

TOKENS = {
    "athlete-token": Principal(user_id=1, role=UserRole.ATHLETE),
    "admin-token": Principal(user_id=2, role=UserRole.ADMIN),
}


class _FakeVerifier:
    async def verify(self, token: str) -> Principal:
        if token not in TOKENS:
            raise DomainError(ErrorReason.ERROR_REASON_UNAUTHORIZED, "Invalid or expired access token")
        return TOKENS[token]


class _PrincipalSystem(SystemServicer):
    """Responde WakeUpAi solo para comprobar quién llegó al handler."""

    def __init__(self, seen: list[Principal]) -> None:
        super().__init__(lambda: datetime.now(timezone.utc), GetClientPolicyResponse(), UnavailableAiLifecycle())
        self._seen = seen

    async def WakeUpAi(self, request, context):
        self._seen.append(current_principal())
        return system_pb2.WakeUpAiResponse()


class _PrincipalAnalysis(analysis_pb2_grpc.AnalysisServiceServicer):
    async def WatchAnalysis(self, request, context):
        for _ in range(2):
            await asyncio.sleep(0)
            yield analysis_pb2.WatchAnalysisResponse(
                progress=movement_pb2.AnalysisProgress(frames_processed=current_principal().user_id)
            )


def _register(seen: list[Principal]):
    def register(server: grpc.aio.Server) -> None:
        system_pb2_grpc.add_SystemServiceServicer_to_server(_PrincipalSystem(seen), server)
        user_admin_pb2_grpc.add_UserAdminServiceServicer_to_server(user_admin_pb2_grpc.UserAdminServiceServicer(), server)
        analysis_pb2_grpc.add_AnalysisServiceServicer_to_server(_PrincipalAnalysis(), server)

    return register


def _interceptors() -> list[grpc.aio.ServerInterceptor]:
    return [ErrorInterceptor(), AuthInterceptor(_FakeVerifier())]


def _bearer(token: str) -> tuple[tuple[str, str], ...]:
    return (("authorization", f"Bearer {token}"),)


async def _error_of(call) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await call
    return raised.value


def test_access_policy_is_read_from_the_contract() -> None:
    assert access_for("/kinesiapp.system.v1.SystemService/Ping").public
    assert access_for("/kinesiapp.system.v1.SystemService/WakeUpAi").roles == frozenset()
    assert access_for("/kinesiapp.admin.v1.UserAdminService/GetUser").roles == {UserRole.ADMIN}


def test_public_method_needs_no_token() -> None:
    async def call() -> str:
        async with serving(_register([]), _interceptors()) as channel:
            response = await system_pb2_grpc.SystemServiceStub(channel).Ping(system_pb2.PingRequest(message="hola"))
        return response.message

    assert asyncio.run(call()) == "hola"


def test_method_without_option_rejects_missing_or_invalid_tokens() -> None:
    async def call() -> list[grpc.aio.AioRpcError]:
        async with serving(_register([]), _interceptors()) as channel:
            stub = system_pb2_grpc.SystemServiceStub(channel)
            return [
                await _error_of(stub.WakeUpAi(system_pb2.WakeUpAiRequest())),
                await _error_of(stub.WakeUpAi(system_pb2.WakeUpAiRequest(), metadata=_bearer("forged"))),
            ]

    for error in asyncio.run(call()):
        assert error.code() == grpc.StatusCode.UNAUTHENTICATED
        assert error_info(error).reason == "UNAUTHORIZED"


def test_valid_token_reaches_the_handler_with_its_principal() -> None:
    seen: list[Principal] = []

    async def call() -> None:
        async with serving(_register(seen), _interceptors()) as channel:
            await system_pb2_grpc.SystemServiceStub(channel).WakeUpAi(
                system_pb2.WakeUpAiRequest(), metadata=_bearer("athlete-token")
            )

    asyncio.run(call())

    assert seen == [TOKENS["athlete-token"]]


def test_roles_from_the_contract_are_enforced() -> None:
    async def call() -> tuple[grpc.aio.AioRpcError, grpc.aio.AioRpcError]:
        async with serving(_register([]), _interceptors()) as channel:
            stub = user_admin_pb2_grpc.UserAdminServiceStub(channel)
            request = user_admin_pb2.GetUserRequest(user_id=1)
            return (
                await _error_of(stub.GetUser(request, metadata=_bearer("athlete-token"))),
                await _error_of(stub.GetUser(request, metadata=_bearer("admin-token"))),
            )

    as_athlete, as_admin = asyncio.run(call())

    assert as_athlete.code() == grpc.StatusCode.PERMISSION_DENIED
    assert error_info(as_athlete).reason == "FORBIDDEN"
    # El admin pasa el interceptor y llega al servicer base, que todavía no está implementado
    assert as_admin.code() == grpc.StatusCode.UNIMPLEMENTED


def test_principal_stays_bound_across_stream_messages() -> None:
    async def call() -> list[int]:
        async with serving(_register([]), _interceptors()) as channel:
            stream = analysis_pb2_grpc.AnalysisServiceStub(channel).WatchAnalysis(
                analysis_pb2.WatchAnalysisRequest(analysis_id=1), metadata=_bearer("admin-token")
            )
            return [response.progress.frames_processed async for response in stream]

    assert asyncio.run(call()) == [2, 2]
