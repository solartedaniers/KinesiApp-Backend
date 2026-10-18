import logging
from collections.abc import AsyncIterator
from typing import Protocol

import grpc
from kinesiapp.ai.v1 import movement_analysis_pb2
from kinesiapp.common.v1 import movement_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.transport import AiCallError, AiTransport
from app.analysis.progress import AnalysisProgressUpdate
from app.models.jump_analysis import AnalysisStage, MovementType

logger = logging.getLogger(__name__)

_ANALYZE = movement_analysis_pb2.DESCRIPTOR.services_by_name["MovementAnalysisService"].methods_by_name["AnalyzeVideo"]
_UNAVAILABLE = ErrorReason.Name(ErrorReason.ERROR_REASON_AI_UNAVAILABLE).removeprefix("ERROR_REASON_")
_BUSY = ErrorReason.Name(ErrorReason.ERROR_REASON_AI_BUSY).removeprefix("ERROR_REASON_")
_CONTRACT_REASONS = frozenset(name.removeprefix("ERROR_REASON_") for name in ErrorReason.keys())

# Cada evento es un avance o, al final, el resultado completo de la IA
AnalyzerEvent = AnalysisProgressUpdate | movement_analysis_pb2.MovementAnalysisResult


class AnalyzerError(Exception):
    """La IA no entregó el resultado. reason es el nombre del ErrorReason que guardo en el análisis FAILED."""

    def __init__(self, reason: str, retryable: bool, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.retryable = retryable


class MovementAnalyzer(Protocol):
    def analyze(self, video_url: str, movement_type: MovementType) -> AsyncIterator[AnalyzerEvent]: ...


class RemoteMovementAnalyzer:
    """Adapter de MovementAnalyzer sobre el MovementAnalysisService de la IA.

    Decido aquí qué fallos se reintentan porque solo aquí conozco los status de gRPC: AI_BUSY y cualquier
    UNAVAILABLE (IA dormida, arrancando o sin poder descargar) son pasajeros; el resto no cambia al repetir.
    """

    def __init__(self, transport: AiTransport, timeout: float) -> None:
        self._transport = transport
        self._timeout = timeout

    async def analyze(self, video_url: str, movement_type: MovementType) -> AsyncIterator[AnalyzerEvent]:
        request = movement_analysis_pb2.AnalyzeVideoRequest(
            video_url=video_url, movement_type=movement_pb2.MovementType.Value(f"MOVEMENT_TYPE_{movement_type.name}")
        )
        replies = self._transport.server_stream(_ANALYZE, request, movement_analysis_pb2.AnalyzeVideoResponse, self._timeout)
        try:
            async for reply in replies:
                if reply.HasField("result"):
                    yield reply.result
                    return
                yield _progress(reply.progress)
        except AiCallError as error:
            raise _analyzer_error(error) from error
        raise AnalyzerError(_UNAVAILABLE, True, "The AI closed the stream without a result")


def _progress(progress: movement_pb2.AnalysisProgress) -> AnalysisProgressUpdate:
    stage = AnalysisStage[movement_pb2.AnalysisStage.Name(progress.stage).removeprefix("ANALYSIS_STAGE_")]
    return AnalysisProgressUpdate(stage, progress.frames_processed, progress.frames_total)


def _analyzer_error(error: AiCallError) -> AnalyzerError:
    retryable = error.code is grpc.StatusCode.UNAVAILABLE or error.reason == _BUSY
    if error.reason in _CONTRACT_REASONS and error.code is not grpc.StatusCode.UNAUTHENTICATED:
        return AnalyzerError(error.reason, retryable, error.message)
    # Un token que no coincide o un fallo sin reason es problema de la IA, no del video
    logger.error("Movement analysis call failed: %s", error)
    return AnalyzerError(_UNAVAILABLE, retryable, error.message)
