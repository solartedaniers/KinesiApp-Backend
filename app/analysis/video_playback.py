import logging
from collections.abc import Callable

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.analysis.analysis_access import visible_analysis
from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.repositories.unit_of_work import UnitOfWork
from app.storage.signed_storage import PresignedRead, SignedObjectStorage

logger = logging.getLogger(__name__)


class VideoPlayback:
    """Firmo una URL de lectura de vida corta para reproducir el video de un análisis visible."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], videos: SignedObjectStorage) -> None:
        self._uow_factory = uow_factory
        self._videos = videos

    async def link(self, principal: Principal, analysis_id: int) -> PresignedRead:
        async with self._uow_factory() as uow:
            analysis = await visible_analysis(uow, principal, analysis_id)
        try:
            key = self._videos.key_from_url(analysis.video_reference)
        except ValueError as error:
            # No firmo los videos del REST: viven en el bucket público de producción
            logger.warning("Video of analysis %s is outside the private bucket", analysis_id)
            raise DomainError(ErrorReason.ERROR_REASON_NOT_FOUND, "The video is not available") from error
        return self._videos.presign_read(key)
