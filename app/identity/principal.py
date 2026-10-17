from contextvars import ContextVar, Token
from dataclasses import dataclass

from app.models.user import UserRole


@dataclass(frozen=True)
class Principal:
    """Quién hace la llamada, ya autenticado por el interceptor."""

    user_id: int
    role: UserRole


# Uso un ContextVar porque cada llamada gRPC corre en su propia tarea de asyncio: no se cruza entre llamadas
_current_principal: ContextVar[Principal] = ContextVar("current_principal")


def current_principal() -> Principal:
    return _current_principal.get()


def bind_principal(principal: Principal) -> Token[Principal]:
    return _current_principal.set(principal)


def unbind_principal(token: Token[Principal]) -> None:
    _current_principal.reset(token)
