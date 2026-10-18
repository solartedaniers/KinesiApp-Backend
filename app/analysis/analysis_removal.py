import logging
from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.analysis.analysis_access import manages_recordings, visible_analysis
from app.analysis.analysis_runner import AnalysisRunner
from app.analysis.progress import AnalysisFinished
from app.analysis.progress_hub import AnalysisProgressHub
from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.user import UserRole
from app.repositories.unit_of_work import UnitOfWork
from app.storage.signed_storage import SignedObjectStorage

logger = logging.getLogger(__name__)


class AnalysisRemoval:
    """Borro un análisis con sus mediciones y su conversación, detengo su procesamiento y quito su video del bucket."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        videos: SignedObjectStorage,
        runner: AnalysisRunner,
        hub: AnalysisProgressHub,
    ) -> None:
        self._uow_factory = uow_factory
        self._videos = videos
        self._runner = runner
        self._hub = hub

    async def delete(self, principal: Principal, analysis_id: int) -> None:
        async with self._uow_factory() as uow:
            analysis = await visible_analysis(uow, principal, analysis_id)
            if principal.role is not UserRole.ADMIN and not manages_recordings(principal, analysis.athlete):
                raise DomainError(ErrorReason.ERROR_REASON_FORBIDDEN, "You cannot delete this analysis")
            video_reference = analysis.video_reference
            await uow.analyses.delete(analysis)
            await uow.commit()
        self._runner.cancel(analysis_id)
        # Despierto a quien lo estaba siguiendo para que reciba NOT_FOUND en vez de esperar para siempre
        self._hub.publish(analysis_id, AnalysisFinished(analysis_id))
        await self._discard(video_reference)

    async def _discard(self, video_reference: str) -> None:
        # Lo hago después del commit: si falla, solo queda un objeto huérfano, nunca un análisis sin video
        try:
            await self._videos.delete(self._videos.key_from_url(video_reference))
        except (DomainError, ValueError) as error:
            logger.warning("Could not delete video %s: %s", video_reference, error)
