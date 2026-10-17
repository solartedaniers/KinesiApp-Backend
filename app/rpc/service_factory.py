from collections.abc import Callable
from datetime import datetime, timezone
from functools import partial

import grpc
from kinesiapp.system.v1 import system_pb2_grpc

from app.ai.lifecycle import UnavailableAiLifecycle
from app.identity.password_policy import PasswordPolicy
from app.rpc.client_policy import build_client_policy
from app.rpc.system_servicer import SystemServicer
from app.settings.athlete import AthleteSettings
from app.settings.auth import PasswordPolicySettings
from app.settings.chat import ChatSettings
from app.settings.storage import MediaSettings

Registration = Callable[[grpc.aio.Server], None]


class RpcServiceFactory:
    """Factory: arma cada servicer con sus dependencias a partir de la configuración de su dominio."""

    def registrations(self) -> list[Registration]:
        return [partial(system_pb2_grpc.add_SystemServiceServicer_to_server, self._system())]

    @staticmethod
    def _clock() -> datetime:
        return datetime.now(timezone.utc)

    def _system(self) -> SystemServicer:
        client_policy = build_client_policy(
            MediaSettings(), PasswordPolicy(PasswordPolicySettings()), AthleteSettings(), ChatSettings()
        )
        return SystemServicer(self._clock, client_policy, UnavailableAiLifecycle())
