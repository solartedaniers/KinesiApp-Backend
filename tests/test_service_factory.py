from sqlalchemy.ext.asyncio import async_sessionmaker

from app.rpc.service_factory import RpcServiceFactory
from tests.rpc_world import AUTH_SETTINGS


class _RecordingServer:
    def __init__(self) -> None:
        self.services: list[str] = []

    def add_generic_rpc_handlers(self, handlers) -> None:
        self.services.extend(handler.service_name() for handler in handlers)

    def add_registered_method_handlers(self, service_name, handlers) -> None:
        pass


def test_factory_registers_every_migrated_service() -> None:
    # Con las variables ficticias de conftest el bucket queda sin configurar, y aun así todo debe armarse
    server = _RecordingServer()
    for register in RpcServiceFactory(async_sessionmaker(), AUTH_SETTINGS).registrations():
        register(server)

    assert server.services == [
        "kinesiapp.system.v1.SystemService",
        "kinesiapp.auth.v1.AuthService",
        "kinesiapp.account.v1.AccountService",
        "kinesiapp.admin.v1.UserAdminService",
    ]
