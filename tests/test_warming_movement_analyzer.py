"""Pruebo que WarmingMovementAnalyzer despierte la IA antes de abrir el stream y que, si no despierta, el fallo se reintente."""

import asyncio

import pytest
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.lifecycle import AiState
from app.ai.remote_movement_analyzer import AnalyzerError
from app.ai.warming_movement_analyzer import WarmingMovementAnalyzer
from app.core.domain_error import DomainError
from app.models.jump_analysis import MovementType


class _Lifecycle:
    def __init__(self, calls: list[str], awake: bool = True) -> None:
        self._calls = calls
        self._awake = awake

    async def wake_up(self) -> AiState:
        self._calls.append("wake_up")
        if not self._awake:
            raise DomainError(ErrorReason.ERROR_REASON_AI_UNAVAILABLE, "asleep")
        return AiState.READY


class _Analyzer:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def analyze(self, video_url: str, movement_type: MovementType):
        self._calls.append("analyze")
        yield "result"


def _run(awake: bool) -> tuple[list[str], list[str]]:
    calls: list[str] = []
    analyzer = WarmingMovementAnalyzer(_Lifecycle(calls, awake), _Analyzer(calls))

    async def main():
        return [event async for event in analyzer.analyze("https://bucket.test/v.mp4", MovementType.SQUAT)]

    return calls, asyncio.run(main())


def test_the_ai_wakes_up_before_the_analysis_stream_opens() -> None:
    calls, events = _run(awake=True)

    assert calls == ["wake_up", "analyze"] and events == ["result"]


def test_an_ai_that_does_not_wake_up_is_a_retryable_failure_without_opening_the_stream() -> None:
    with pytest.raises(AnalyzerError) as caught:
        _run(awake=False)

    assert (caught.value.reason, caught.value.retryable) == ("AI_UNAVAILABLE", True)
