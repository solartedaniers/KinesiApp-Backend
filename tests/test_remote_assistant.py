"""Pruebo por gRPC-Web el adaptador del asistente: el texto llega por partes y cada fallo sale con su motivo."""

import asyncio

import grpc
import httpx
import pytest
from kinesiapp.ai.v1 import assistant_pb2, assistant_pb2_grpc
from kinesiapp.common.v1 import chat_pb2, identity_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.grpc_web_transport import GrpcWebTransport
from app.ai.remote_assistant import AssistantFailure, AssistantReply, RemoteAnalysisAssistant
from app.models.chat import ChatMessage, ChatRole
from app.models.user import UserRole
from tests.ai_world import AI_TOKEN, abort_with_reason, ai_world, require_token

FACTS = assistant_pb2.AnalysisFacts(risk_score=0.7, dominant_risk_pattern="rigid_landing")


class _Assistant(assistant_pb2_grpc.AssistantServiceServicer):
    def __init__(self, fail: str | None = None, finish: bool = True) -> None:
        self._fail = fail
        self._finish = finish
        self.questions: list[assistant_pb2.AnswerQuestionRequest] = []

    async def ExplainAnalysis(self, request, context):
        await require_token(context)
        for delta in ("Tu aterrizaje ", "es rígido."):
            yield assistant_pb2.ExplainAnalysisResponse(text_delta=delta)
        if self._fail:
            code = grpc.StatusCode.UNAVAILABLE if self._fail == "ASSISTANT_UNAVAILABLE" else grpc.StatusCode.RESOURCE_EXHAUSTED
            await abort_with_reason(context, code, self._fail)
        if self._finish:
            reply = assistant_pb2.AssistantReply(content="Tu aterrizaje es rígido.", prompt_version="v3")
            yield assistant_pb2.ExplainAnalysisResponse(reply=reply)

    async def AnswerQuestion(self, request, context):
        await require_token(context)
        self.questions.append(request)
        yield assistant_pb2.AnswerQuestionResponse(reply=assistant_pb2.AssistantReply(content="Sí.", prompt_version="v3"))


def _collect(assistant: _Assistant, call):
    async def main():
        register = lambda server: assistant_pb2_grpc.add_AssistantServiceServicer_to_server(assistant, server)
        async with ai_world([register]) as endpoints:
            transport = GrpcWebTransport(httpx.AsyncClient(trust_env=False), endpoints.grpc_web_url, AI_TOKEN, 5)
            try:
                return [event async for event in call(RemoteAnalysisAssistant(transport, timeout=5))]
            finally:
                await transport.aclose()

    return asyncio.run(main())


def test_the_explanation_arrives_in_parts_and_ends_with_the_full_reply() -> None:
    events = _collect(_Assistant(), lambda remote: remote.explain(FACTS, UserRole.ATHLETE))

    assert events == ["Tu aterrizaje ", "es rígido.", AssistantReply("Tu aterrizaje es rígido.", "v3")]


def test_the_question_travels_with_the_history_and_the_audience() -> None:
    assistant = _Assistant()
    history = [ChatMessage(role=ChatRole.ASSISTANT, content="Hola"), ChatMessage(role=ChatRole.USER, content="¿Y?")]

    _collect(assistant, lambda remote: remote.answer(FACTS, UserRole.COACH, history, "¿Es grave?"))

    sent = assistant.questions[0]
    assert (sent.question, sent.audience) == ("¿Es grave?", identity_pb2.USER_ROLE_COACH)
    assert [(turn.role, turn.content) for turn in sent.history] == [
        (chat_pb2.CHAT_ROLE_ASSISTANT, "Hola"),
        (chat_pb2.CHAT_ROLE_USER, "¿Y?"),
    ]
    assert sent.facts == FACTS


@pytest.mark.parametrize(
    ("assistant", "reason", "retryable"),
    [
        (_Assistant(fail="ASSISTANT_UNAVAILABLE"), ErrorReason.ERROR_REASON_ASSISTANT_UNAVAILABLE, False),
        (_Assistant(fail="ASSISTANT_BUSY"), ErrorReason.ERROR_REASON_ASSISTANT_BUSY, False),
        (_Assistant(fail="ASSISTANT_DAILY_LIMIT"), ErrorReason.ERROR_REASON_ASSISTANT_DAILY_LIMIT, False),
        (_Assistant(finish=False), ErrorReason.ERROR_REASON_ASSISTANT_UNAVAILABLE, True),
    ],
    ids=["ai-unavailable", "ai-busy", "ai-daily-limit", "cut-without-reply"],
)
def test_each_failure_keeps_its_reason_and_only_a_cut_stream_is_retryable(assistant: _Assistant, reason, retryable) -> None:
    with pytest.raises(AssistantFailure) as caught:
        _collect(assistant, lambda remote: remote.explain(FACTS, UserRole.ATHLETE))

    assert (caught.value.reason, caught.value.retryable) == (reason, retryable)
