import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from app.analysis.analysis_runner import AnalysisRunner
from app.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class StalledAnalysisRecovery:
    """Retomo los análisis PENDING que una instancia dejó a medias, al arrancar y después cada tanto
    mientras quede alguno que no haya podido tomar.

    Solo tomo los que tienen el lease vencido: uno con el lease vigente es de una instancia viva, como la
    anterior que Render mantiene mientras arranca la nueva. El reclamo atómico decide si de verdad me toca, y
    los que ya agotaron sus intentos los cierra el procesamiento como FAILED.
    """

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], runner: AnalysisRunner, lease: float, clock: Callable[[], datetime]
    ) -> None:
        self._uow_factory = uow_factory
        self._runner = runner
        self._lease = timedelta(seconds=lease)
        self._clock = clock

    async def watch(self, interval: float, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        # Repito porque, si la instancia dueña muere después de mi arranque, nadie más lo retomaría. Paro cuando
        # no queda ningún PENDING en otras manos: así, sin análisis en curso, no despierto a Neon cada minuto
        while True:
            try:
                resumed, pending = await self._scan()
                if pending <= resumed:
                    return
            except Exception:
                logger.exception("Stalled analysis recovery failed")
            await sleep(interval)

    async def recover(self) -> int:
        resumed, _ = await self._scan()
        return resumed

    async def _scan(self) -> tuple[int, int]:
        now = self._clock()
        async with self._uow_factory() as uow:
            stalled = await uow.analyses.list_recoverable(now, now - self._lease)
            pending = await uow.analyses.count_pending()
        for analysis in stalled:
            self._runner.submit(analysis.id)
        if stalled:
            logger.info("Resumed %s stalled analyses", len(stalled))
        return len(stalled), pending
