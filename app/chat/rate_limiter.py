from collections.abc import Callable
from datetime import datetime, timedelta

from app.repositories.chat_repository import ChatMessageRepository


class ChatRateLimitedError(Exception):
    pass


class ChatRateLimiter:
    """Cuenta los mensajes de usuario ya guardados en Postgres (§6.7), sin tabla de contadores.

    Límite blando: dos requests simultáneos pueden pasarlo por uno, aceptable con tráfico de demo.
    """

    def __init__(
        self,
        messages: ChatMessageRepository,
        per_conversation_per_hour: int,
        global_per_minute: int,
        now: Callable[[], datetime],
    ) -> None:
        self._messages = messages
        self._per_conversation_per_hour = per_conversation_per_hour
        self._global_per_minute = global_per_minute
        self._now = now

    def check(self, conversation_id: int) -> None:
        now = self._now()
        if self._messages.count_user_messages_since(now - timedelta(hours=1), conversation_id) >= self._per_conversation_per_hour:
            raise ChatRateLimitedError("Conversation hourly limit reached")
        if self._messages.count_user_messages_since(now - timedelta(minutes=1)) >= self._global_per_minute:
            raise ChatRateLimitedError("Global per-minute limit reached")
