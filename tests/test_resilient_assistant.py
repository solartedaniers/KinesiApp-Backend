"""Pruebo que ResilientAssistant despierte la IA y reintente solo cuando la conexión se corta antes de dar texto."""

import asyncio

import pytest
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.lifecycle import AiState
from app.ai.remote_assistant import AssistantFailure, AssistantReply
from app.ai.resilient_assistant import ResilientAssistant
from app.core.domain_error import DomainError
from app.models.user import UserRole

_UNAVAILABLE = ErrorReason.ERROR_REASON_ASSISTANT_UNAVAILABLE


class _Lifecycle:
    def __init__(self, calls: list[str], awake: bool = True) -> None:
        self._calls, self._awake = calls, awake

    async def wake_up(self) -> AiState:
        self._calls.append("wake_up")
        if not self._awake:
            raise DomainError(ErrorReason.ERROR_REASON_AI_UNAVAILABLE, "asleep")
        return AiState.READY


class _Assistant:
    """Cada intento sigue un guion: "silent" se corta sin texto, "cut" se corta después de un fragmento, "busy" es la
    IA que ya probó sus dos modelos y "ok" responde."""

    def __init__(self, calls: list[str], script: list[str]) -> None:
        self._calls, self._script = calls, script

    async def answer(self, facts, audience, history, question):
        outcome = self._script.pop(0)
        self._calls.append(f"answer:{outcome}")
        if outcome == "cut":
            yield "Primera parte"
        if outcome == "busy":
            raise AssistantFailure(ErrorReason.ERROR_REASON_ASSISTANT_BUSY, outcome, retryable=False)
        if outcome != "ok":
            raise AssistantFailure(_UNAVAILABLE, outcome, retryable=True)
        yield "Respuesta"
        yield AssistantReply("Respuesta", "prompt-v1")


def _ask(script: list[str], calls: list[str], awake: bool = True) -> list:
    assistant = ResilientAssistant(_Lifecycle(calls, awake), _Assistant(calls, script), attempts=2)

    async def main():
        return [event async for event in assistant.answer(None, UserRole.ATHLETE, [], "¿Y el tronco?")]

    return asyncio.run(main())


def test_the_ai_wakes_up_before_the_stream_opens() -> None:
    calls: list[str] = []

    received = _ask(["ok"], calls)

    assert calls == ["wake_up", "answer:ok"] and received[0] == "Respuesta"


def test_a_connection_cut_before_any_text_is_retried_once_and_the_second_attempt_answers() -> None:
    calls: list[str] = []

    received = _ask(["silent", "ok"], calls)

    assert calls == ["wake_up", "answer:silent", "wake_up", "answer:ok"]
    assert received == ["Respuesta", AssistantReply("Respuesta", "prompt-v1")]


def test_after_the_last_attempt_the_failure_reaches_the_caller() -> None:
    with pytest.raises(DomainError) as caught:
        _ask(["silent", "silent"], [])

    assert caught.value.reason == _UNAVAILABLE


def test_a_failure_after_text_is_not_retried_so_the_answer_is_not_duplicated() -> None:
    calls: list[str] = []

    with pytest.raises(DomainError):
        _ask(["cut", "ok"], calls)

    assert calls == ["wake_up", "answer:cut"]


def test_if_the_ai_does_not_wake_up_the_assistant_is_not_called() -> None:
    calls: list[str] = []

    with pytest.raises(DomainError) as caught:
        _ask(["ok"], calls, awake=False)

    assert caught.value.reason == ErrorReason.ERROR_REASON_AI_UNAVAILABLE and calls == ["wake_up"]


def test_when_the_ai_already_tried_both_models_the_failure_is_not_retried() -> None:
    # Reproduzco el 21-oct: reintentar sumaba otros 24 s sin cambiar el resultado
    calls: list[str] = []

    with pytest.raises(AssistantFailure) as caught:
        _ask(["busy", "ok"], calls)

    assert caught.value.reason == ErrorReason.ERROR_REASON_ASSISTANT_BUSY and calls == ["wake_up", "answer:busy"]
