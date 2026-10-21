import logging
from collections.abc import AsyncIterator, Callable

from kinesiapp.ai.v1 import assistant_pb2

from app.ai.lifecycle import AiLifecycle
from app.ai.remote_assistant import AnalysisAssistant, AssistantEvent, AssistantFailure
from app.models.chat import ChatMessage
from app.models.user import UserRole

logger = logging.getLogger(__name__)


class ResilientAssistant:
    """Decorator de AnalysisAssistant: despierto la IA antes del stream y, si la conexión se corta antes del primer
    texto, reintento.

    Despierto primero porque el ingress de Azure corta el stream que despierta la réplica. Solo reintento cortes de
    conexión: si la IA respondió con un error ya probó sus dos modelos, y otro intento solo alargaba la espera
    (el 21-oct, 48 s por pregunta). A mitad de la respuesta tampoco: el cliente ya recibió texto y lo duplicaría.
    """

    def __init__(self, lifecycle: AiLifecycle, assistant: AnalysisAssistant, attempts: int) -> None:
        self._lifecycle = lifecycle
        self._assistant = assistant
        self._attempts = attempts

    def explain(self, facts: assistant_pb2.AnalysisFacts, audience: UserRole) -> AsyncIterator[AssistantEvent]:
        return self._resilient(lambda: self._assistant.explain(facts, audience))

    def answer(
        self, facts: assistant_pb2.AnalysisFacts, audience: UserRole, history: list[ChatMessage], question: str
    ) -> AsyncIterator[AssistantEvent]:
        return self._resilient(lambda: self._assistant.answer(facts, audience, history, question))

    async def _resilient(self, start: Callable[[], AsyncIterator[AssistantEvent]]) -> AsyncIterator[AssistantEvent]:
        for attempt in range(1, self._attempts + 1):
            await self._lifecycle.wake_up()
            sent = False
            try:
                async for event in start():
                    sent = True
                    yield event
                return
            except AssistantFailure as error:
                if sent or not error.retryable or attempt == self._attempts:
                    raise
                logger.warning("Assistant attempt %d lost the connection before any text, retrying: %s", attempt, error)
