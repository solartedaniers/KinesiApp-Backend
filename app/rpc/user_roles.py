from kinesiapp.common.v1 import identity_pb2

from app.models.user import UserRole

_ROLE_PREFIX = "USER_ROLE_"


def role_from_proto(role: identity_pb2.UserRole.ValueType) -> UserRole | None:
    # None para USER_ROLE_UNSPECIFIED: el validador de cada request decide si eso es un error
    return UserRole.__members__.get(identity_pb2.UserRole.Name(role).removeprefix(_ROLE_PREFIX))


def role_to_proto(role: UserRole) -> identity_pb2.UserRole.ValueType:
    return identity_pb2.UserRole.Value(f"{_ROLE_PREFIX}{role.name}")
