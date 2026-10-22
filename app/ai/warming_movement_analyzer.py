from collections.abc import AsyncIterator

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.lifecycle import AiLifecycle
from app.ai.remote_movement_analyzer import AnalyzerError, AnalyzerEvent, MovementAnalyzer
from app.core.domain_error import DomainError
from app.models.jump_analysis import MovementType

_UNAVAILABLE = ErrorReason.Name(ErrorReason.ERROR_REASON_AI_UNAVAILABLE).removeprefix("ERROR_REASON_")


class WarmingMovementAnalyzer:
    """Decorator de MovementAnalyzer: despierto la IA con WarmUp antes de abrir el stream del análisis.

    Lo hago porque el ingress de Azure resetea a mitad del análisis el stream que despierta la réplica desde
    cero (RST_STREAM a los ~40 s); con la réplica ya arriba, el mismo stream llega completo.
    """

    def __init__(self, lifecycle: AiLifecycle, analyzer: MovementAnalyzer) -> None:
        self._lifecycle = lifecycle
        self._analyzer = analyzer

    async def analyze(self, video_url: str, movement_type: MovementType) -> AsyncIterator[AnalyzerEvent]:
        try:
            await self._lifecycle.wake_up()
        except DomainError as error:
            raise AnalyzerError(_UNAVAILABLE, True, str(error)) from error
        async for event in self._analyzer.analyze(video_url, movement_type):
            yield event
