import importlib
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.rpc.service_factory import RpcServiceFactory
from tests.rpc_world import AUTH_SETTINGS

GENERATED = Path(__file__).resolve().parents[1] / "generated"
# Dejo fuera los servicios de la IA: los sirve su propio microservicio, no este backend
FOREIGN_PACKAGES = {"kinesiapp.ai.v1"}
# Dominios del contrato que aún no migro; la lista debe quedar vacía al terminar la migración del backend
PENDING_PACKAGES = {"kinesiapp.analysis.v1", "kinesiapp.chat.v1"}


class _RecordingServer:
    def __init__(self) -> None:
        self.services: list[str] = []

    def add_generic_rpc_handlers(self, handlers) -> None:
        self.services.extend(handler.service_name() for handler in handlers)

    def add_registered_method_handlers(self, service_name, handlers) -> None:
        pass


def _registered_services() -> list[str]:
    # Con las variables ficticias de conftest el bucket queda sin configurar, y aun así todo debe armarse
    server = _RecordingServer()
    for register in RpcServiceFactory(async_sessionmaker(), AUTH_SETTINGS).registrations():
        register(server)
    return server.services


def _contract_services() -> set[str]:
    services = set()
    for module_path in GENERATED.glob("kinesiapp/*/v1/*_pb2.py"):
        module_name = ".".join(module_path.relative_to(GENERATED).with_suffix("").parts)
        for service in importlib.import_module(module_name).DESCRIPTOR.services_by_name.values():
            services.add(service.full_name)
    return services


def test_factory_registers_every_migrated_service() -> None:
    assert _registered_services() == [
        "kinesiapp.system.v1.SystemService",
        "kinesiapp.auth.v1.AuthService",
        "kinesiapp.account.v1.AccountService",
        "kinesiapp.admin.v1.UserAdminService",
        "kinesiapp.athlete.v1.AthleteProfileService",
        "kinesiapp.athlete.v1.ManagedAthleteService",
        "kinesiapp.team.v1.TeamService",
    ]


def test_every_backend_service_in_the_contracts_is_registered_or_pending() -> None:
    def package(service: str) -> str:
        return service.rsplit(".", 1)[0]

    expected = {s for s in _contract_services() if package(s) not in FOREIGN_PACKAGES}
    registered = set(_registered_services())
    missing = {s for s in expected - registered if package(s) not in PENDING_PACKAGES}

    assert missing == set()
    assert registered <= expected
    # Si ya registré un dominio pendiente, lo saco de la lista para que no se quede ahí sin necesidad
    assert {package(s) for s in registered} & PENDING_PACKAGES == set()
    assert PENDING_PACKAGES <= {package(s) for s in expected}
