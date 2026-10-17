from dataclasses import dataclass
from functools import lru_cache

from google.protobuf import descriptor_pool
from kinesiapp.common.v1 import identity_pb2

from app.models.user import UserRole
from app.rpc.user_roles import role_from_proto


@dataclass(frozen=True)
class MethodAccess:
    public: bool
    # Lo dejo vacío para admitir cualquier rol con sesión iniciada
    roles: frozenset[UserRole]


@lru_cache
def access_for(method: str) -> MethodAccess:
    """Leo la opción (kinesiapp.common.v1.access) del RPC. method llega como "/paquete.Servicio/Metodo"."""
    full_name = method.lstrip("/").replace("/", ".")
    try:
        options = descriptor_pool.Default().FindMethodByName(full_name).GetOptions()
    except KeyError:
        # Nunca trato como público por omisión un método fuera del contrato
        return MethodAccess(public=False, roles=frozenset())
    if not options.HasExtension(identity_pb2.access):
        return MethodAccess(public=False, roles=frozenset())
    policy = options.Extensions[identity_pb2.access]
    roles = frozenset(role for role in map(role_from_proto, policy.roles) if role is not None)
    return MethodAccess(public=policy.public, roles=roles)
