import asyncio
from datetime import datetime, timezone

import grpc
import pytest
from kinesiapp.common.v1 import ai_state_pb2
from kinesiapp.system.v1 import system_pb2, system_pb2_grpc

from app.ai.lifecycle import AiState
from app.identity.password_policy import PasswordPolicy
from app.rpc.client_policy import build_client_policy
from app.rpc.interceptors.errors import ErrorInterceptor
from app.rpc.system_servicer import SystemServicer
from app.settings.athlete import AthleteSettings
from app.settings.auth import PasswordPolicySettings
from app.settings.chat import ChatSettings
from app.settings.storage import MediaSettings
from tests.ai_world import UnreachableAi
from tests.grpc_harness import error_info, serving

FIXED_TIME = datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)


class _ReadyAi:
    async def wake_up(self) -> AiState:
        return AiState.READY


def _client_policy() -> system_pb2.GetClientPolicyResponse:
    return build_client_policy(
        MediaSettings(_env_file=None, MAX_VIDEO_DURATION_SECONDS=40, MAX_VIDEO_UPLOAD_BYTES=50_000_000),
        PasswordPolicy(PasswordPolicySettings(_env_file=None, PASSWORD_MIN_LENGTH=10)),
        AthleteSettings(_env_file=None),
        ChatSettings(_env_file=None, CHAT_MESSAGE_MAX_CHARS=500),
    )


def _stub_call(ai_lifecycle, call):
    async def run():
        servicer = SystemServicer(lambda: FIXED_TIME, _client_policy(), ai_lifecycle)

        def register(server: grpc.aio.Server) -> None:
            system_pb2_grpc.add_SystemServiceServicer_to_server(servicer, server)

        async with serving(register, [ErrorInterceptor()]) as channel:
            return await call(system_pb2_grpc.SystemServiceStub(channel))

    return asyncio.run(run())


def test_ping_echoes_the_message_with_the_server_time() -> None:
    response = _stub_call(UnreachableAi(), lambda stub: stub.Ping(system_pb2.PingRequest(message="hola")))

    assert response.message == "hola"
    assert response.server_time.ToDatetime(tzinfo=timezone.utc) == FIXED_TIME


def test_client_policy_comes_from_configuration() -> None:
    policy = _stub_call(UnreachableAi(), lambda stub: stub.GetClientPolicy(system_pb2.GetClientPolicyRequest()))

    assert policy.video.max_duration_seconds == 40
    assert policy.video.max_size_bytes == 50_000_000
    assert policy.password.min_length == 10
    assert list(policy.password.requirements) == [
        system_pb2.PASSWORD_REQUIREMENT_UPPERCASE,
        system_pb2.PASSWORD_REQUIREMENT_LOWERCASE,
        system_pb2.PASSWORD_REQUIREMENT_DIGIT,
        system_pb2.PASSWORD_REQUIREMENT_SPECIAL_CHARACTER,
    ]
    assert (policy.athlete_min_age_years, policy.athlete_max_age_years) == (5, 100)
    assert policy.chat_message_max_chars == 500
    biometrics = policy.biometrics
    assert (biometrics.min_height_cm, biometrics.max_height_cm, biometrics.min_weight_kg, biometrics.max_weight_kg) == (80, 250, 15, 250)


def test_athlete_ranges_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="must be lower"):
        AthleteSettings(_env_file=None, ATHLETE_MIN_HEIGHT_CM=200, ATHLETE_MAX_HEIGHT_CM=150)


def test_wake_up_ai_is_unavailable_until_the_ai_service_exists() -> None:
    async def call(stub):
        with pytest.raises(grpc.aio.AioRpcError) as raised:
            await stub.WakeUpAi(system_pb2.WakeUpAiRequest())
        return raised.value

    error = _stub_call(UnreachableAi(), call)

    assert error.code() == grpc.StatusCode.UNAVAILABLE
    assert error_info(error).reason == "AI_UNAVAILABLE"


def test_wake_up_ai_reports_the_state_of_the_ai() -> None:
    response = _stub_call(_ReadyAi(), lambda stub: stub.WakeUpAi(system_pb2.WakeUpAiRequest()))

    assert response.state == ai_state_pb2.AI_STATE_READY
