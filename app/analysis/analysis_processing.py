import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from kinesiapp.ai.v1 import movement_analysis_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.remote_movement_analyzer import AnalyzerError, MovementAnalyzer
from app.analysis.progress import AnalysisFinished, AnalysisProgressUpdate
from app.analysis.progress_hub import AnalysisProgressHub
from app.analysis.retry_policy import RetryPolicy
from app.analysis.risk_assessment_codec import JOINT_NAMES, RiskAssessmentCodec
from app.core.domain_error import DomainError
from app.models.jump_analysis import AnalysisStage, JointAngleMeasurement, JumpAnalysis, JumpAnalysisStatus, MovementType
from app.repositories.unit_of_work import UnitOfWork
from app.storage.signed_storage import SignedObjectStorage

logger = logging.getLogger(__name__)

_UNAVAILABLE = ErrorReason.Name(ErrorReason.ERROR_REASON_AI_UNAVAILABLE).removeprefix("ERROR_REASON_")
_STORAGE_UNAVAILABLE = ErrorReason.Name(ErrorReason.ERROR_REASON_STORAGE_UNAVAILABLE).removeprefix("ERROR_REASON_")
_QUEUED = AnalysisProgressUpdate(AnalysisStage.QUEUED)


@dataclass(frozen=True)
class _Attempt:
    number: int
    video_reference: str
    movement_type: MovementType


class AnalysisProcessing:
    """Proceso un análisis PENDING de punta a punta: pido a la IA, publico y persisto el avance, guardo el
    resultado y reintento con espera creciente lo que la IA no pudo atender.

    Cada paso abre su propia unidad de trabajo: no tengo una transacción abierta durante el minuto que tarda
    la IA, y quien borra el análisis mientras corre no queda bloqueado.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        videos: SignedObjectStorage,
        analyzer: MovementAnalyzer,
        hub: AnalysisProgressHub,
        codec: RiskAssessmentCodec,
        retry: RetryPolicy,
        persist_interval: float,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._uow_factory = uow_factory
        self._videos = videos
        self._analyzer = analyzer
        self._hub = hub
        self._codec = codec
        self._retry = retry
        self._persist_interval = persist_interval
        self._clock = clock
        self._sleep = sleep

    async def process(self, analysis_id: int) -> None:
        while (attempt := await self._start_attempt(analysis_id)) is not None:
            try:
                result = await self._run(analysis_id, attempt)
            except AnalyzerError as error:
                if error.retryable and self._retry.allows(attempt.number + 1):
                    logger.warning("Analysis %s attempt %s failed, retrying: %s", analysis_id, attempt.number, error)
                    self._hub.publish(analysis_id, _QUEUED)
                    await self._sleep(self._retry.delay_before(attempt.number + 1))
                    continue
                logger.warning("Analysis %s failed on attempt %s: %s", analysis_id, attempt.number, error)
                await self._fail(analysis_id, error.reason)
                return
            await self._save(analysis_id, result)
            return

    async def _start_attempt(self, analysis_id: int) -> _Attempt | None:
        async with self._uow_factory() as uow:
            analysis = await uow.analyses.get(analysis_id)
            # Borrado o ya terminado (por ejemplo, otro proceso lo retomó): no hay nada que hacer
            if analysis is None or analysis.status is not JumpAnalysisStatus.PENDING:
                return None
            number = analysis.attempts + 1
            if not self._retry.allows(number):
                self._finish(analysis, JumpAnalysisStatus.FAILED, _UNAVAILABLE)
                await uow.commit()
                self._hub.publish(analysis_id, AnalysisFinished(analysis_id))
                return None
            analysis.attempts = number
            self._record(analysis, _QUEUED)
            await uow.commit()
            return _Attempt(number, analysis.video_reference, analysis.movement_type)

    async def _run(self, analysis_id: int, attempt: _Attempt) -> movement_analysis_pb2.MovementAnalysisResult:
        try:
            video_url = self._videos.presign_read(self._videos.key_from_url(attempt.video_reference)).url
        except (DomainError, ValueError) as error:
            raise AnalyzerError(_STORAGE_UNAVAILABLE, False, str(error)) from error
        persisted: tuple[AnalysisStage, float] | None = None
        async for event in self._analyzer.analyze(video_url, attempt.movement_type):
            if not isinstance(event, AnalysisProgressUpdate):
                return event
            self._hub.publish(analysis_id, event)
            now = asyncio.get_running_loop().time()
            # Escribo al cambiar de etapa y, dentro de una etapa, cada tanto: la base no aguanta cada frame
            if persisted is None or persisted[0] is not event.stage or now - persisted[1] >= self._persist_interval:
                await self._persist_progress(analysis_id, event)
                persisted = (event.stage, now)
        raise AnalyzerError(_UNAVAILABLE, True, "The analyzer finished without a result")

    async def _persist_progress(self, analysis_id: int, update: AnalysisProgressUpdate) -> None:
        async with self._uow_factory() as uow:
            analysis = await uow.analyses.get(analysis_id)
            if analysis is not None and analysis.status is JumpAnalysisStatus.PENDING:
                self._record(analysis, update)
                await uow.commit()

    async def _save(self, analysis_id: int, result: movement_analysis_pb2.MovementAnalysisResult) -> None:
        assessment = result.risk_assessment
        async with self._uow_factory() as uow:
            analysis = await uow.analyses.get(analysis_id)
            if analysis is None or analysis.status is not JumpAnalysisStatus.PENDING:
                return
            analysis.risk_score = assessment.risk_score
            analysis.dominant_risk_pattern = assessment.dominant_pattern if assessment.HasField("dominant_pattern") else None
            analysis.risk_details = self._codec.to_details(assessment)
            analysis.pose_model_version = result.pose_model_version or None
            analysis.risk_model_version = result.risk_model_version or None
            uow.analyses.add_measurements([
                JointAngleMeasurement(
                    jump_analysis_id=analysis_id,
                    joint_name=JOINT_NAMES[sample.joint],
                    angle_degrees=sample.angle_degrees,
                    frame_timestamp_ms=sample.frame_timestamp_ms,
                )
                for sample in result.angle_samples
            ])
            self._finish(analysis, JumpAnalysisStatus.PROCESSED, None)
            await uow.commit()
        self._hub.publish(analysis_id, AnalysisFinished(analysis_id))

    async def _fail(self, analysis_id: int, reason: str) -> None:
        async with self._uow_factory() as uow:
            analysis = await uow.analyses.get(analysis_id)
            if analysis is None or analysis.status is not JumpAnalysisStatus.PENDING:
                return
            self._finish(analysis, JumpAnalysisStatus.FAILED, reason)
            await uow.commit()
        self._hub.publish(analysis_id, AnalysisFinished(analysis_id))

    def _record(self, analysis: JumpAnalysis, update: AnalysisProgressUpdate) -> None:
        analysis.stage = update.stage
        analysis.frames_processed = update.frames_processed
        analysis.frames_total = update.frames_total
        analysis.progress_updated_at = self._clock()

    def _finish(self, analysis: JumpAnalysis, status: JumpAnalysisStatus, reason: str | None) -> None:
        analysis.status = status
        analysis.failure_reason = reason
        analysis.progress_updated_at = self._clock()
