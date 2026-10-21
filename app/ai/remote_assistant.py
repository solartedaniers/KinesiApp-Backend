import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from kinesiapp.ai.v1 import assistant_pb2
from kinesiapp.common.v1 import chat_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.transport import AiCallError, AiTransport
from app.core.domain_error import DomainError
from app.models.chat import ChatMessage, ChatRole
from app.models.user import UserRole
from app.rpc.user_roles import role_to_proto

logger = logging.getLogger(__name__)

_SERVICE = assistant_pb2.DESCRIPTOR.services_by_name["AssistantService"]
_EXPLAIN = _SERVICE.methods_by_name["ExplainAnalysis"]
_ANSWER = _SERVICE.methods_by_name["AnswerQuestion"]
_CHAT_ROLES = {ChatRole.USER: chat_pb2.CHAT_ROLE_USER, ChatRole.ASSISTANT: chat_pb2.CHAT_ROLE_ASSISTANT}


@dataclass(frozen=True)
class AssistantReply:
    content: str
    prompt_version: str


# Cada evento es un fragmento de texto o, al final, la respuesta completa
AssistantEvent = str | AssistantReply

# Motivos que la IA manda cuando ya probó sus dos modelos: los paso tal cual para que la UI diga qué pasó
_PASSED_THROUGH = {
    ErrorReason.Name(reason).removeprefix("ERROR_REASON_"): reason
    for reason in (ErrorReason.ERROR_REASON_ASSISTANT_BUSY, ErrorReason.ERROR_REASON_ASSISTANT_DAILY_LIMIT)
}


class AssistantFailure(DomainError):
    """El asistente no respondió. retryable dice si vale otro intento: solo cuando se cortó la conexión con la IA."""

    def __init__(self, reason: ErrorReason.ValueType, message: str, retryable: bool) -> None:
        super().__init__(reason, message)
        self.retryable = retryable


class AnalysisAssistant(Protocol):
    """El asistente que explica un análisis; si no puede responder, lanzo AssistantFailure."""

    def explain(self, facts: assistant_pb2.AnalysisFacts, audience: UserRole) -> AsyncIterator[AssistantEvent]: ...

    def answer(
        self, facts: assistant_pb2.AnalysisFacts, audience: UserRole, history: list[ChatMessage], question: str
    ) -> AsyncIterator[AssistantEvent]: ...


class RemoteAnalysisAssistant:
    """Adapter de AnalysisAssistant sobre el AssistantService de la IA."""

    def __init__(self, transport: AiTransport, timeout: float) -> None:
        self._transport = transport
        self._timeout = timeout

    def explain(self, facts: assistant_pb2.AnalysisFacts, audience: UserRole) -> AsyncIterator[AssistantEvent]:
        request = assistant_pb2.ExplainAnalysisRequest(facts=facts, audience=role_to_proto(audience))
        return self._relay(self._transport.server_stream(_EXPLAIN, request, assistant_pb2.ExplainAnalysisResponse, self._timeout))

    def answer(
        self, facts: assistant_pb2.AnalysisFacts, audience: UserRole, history: list[ChatMessage], question: str
    ) -> AsyncIterator[AssistantEvent]:
        turns = [assistant_pb2.ConversationTurn(role=_CHAT_ROLES[message.role], content=message.content) for message in history]
        request = assistant_pb2.AnswerQuestionRequest(
            facts=facts, audience=role_to_proto(audience), history=turns, question=question
        )
        return self._relay(self._transport.server_stream(_ANSWER, request, assistant_pb2.AnswerQuestionResponse, self._timeout))

    @staticmethod
    async def _relay(replies: AsyncIterator) -> AsyncIterator[AssistantEvent]:
        finished = False
        try:
            async for reply in replies:
                if reply.HasField("reply"):
                    finished = True
                    yield AssistantReply(reply.reply.content, reply.reply.prompt_version)
                else:
                    yield reply.text_delta
        except AiCallError as error:
            logger.warning("Assistant failed: %s", error)
            raise _failure(error) from error
        # Sin la respuesta final no tengo qué guardar: el stream se cortó antes de terminar
        if not finished:
            raise _unavailable(retryable=True)


def _failure(error: AiCallError) -> AssistantFailure:
    if error.reason in _PASSED_THROUGH:
        return AssistantFailure(_PASSED_THROUGH[error.reason], error.message, retryable=False)
    # Con reason la IA respondió (ya probó su respaldo); sin reason no llegó a responder: corte de red o del ingress
    return _unavailable(retryable=error.reason is None)


def _unavailable(retryable: bool) -> AssistantFailure:
    return AssistantFailure(
        ErrorReason.ERROR_REASON_ASSISTANT_UNAVAILABLE, "The assistant is not available right now", retryable
    )
