from collections.abc import Callable
from datetime import datetime, timedelta

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError
from app.repositories.unit_of_work import UnitOfWork


class ChatUsageLimits:
    """Cuento las preguntas ya guardadas, como el REST: por hilo en la última hora y de todos en el último minuto.

    El tope por hilo es estricto porque lo reviso con el hilo bloqueado. El global es blando: dos hilos
    distintos a la vez pueden pasarlo por uno, y solo protege la cuota del modelo.
    """

    def __init__(self, per_conversation_per_hour: int, global_per_minute: int, clock: Callable[[], datetime]) -> None:
        self._per_conversation_per_hour = per_conversation_per_hour
        self._global_per_minute = global_per_minute
        self._clock = clock

    async def check(self, uow: UnitOfWork, conversation_id: int) -> None:
        now = self._clock()
        in_conversation = await uow.messages.count_user_messages_since(now - timedelta(hours=1), conversation_id)
        if in_conversation >= self._per_conversation_per_hour:
            raise _rate_limited("Conversation hourly limit reached")
        if await uow.messages.count_user_messages_since(now - timedelta(minutes=1)) >= self._global_per_minute:
            raise _rate_limited("Global per-minute limit reached")


def _rate_limited(message: str) -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_CHAT_RATE_LIMITED, message)
