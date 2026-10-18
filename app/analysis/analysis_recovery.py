import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.analysis.analysis_runner import AnalysisRunner
from app.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class StalledAnalysisRecovery:
    """Al arrancar retomo los análisis PENDING que un reinicio dejó a medias.

    Solo tomo los que llevan stale_after sin avance: uno que todavía avanza es de la instancia anterior,
    que Render mantiene viva mientras arranca la nueva. Los que ya agotaron sus intentos los cierra el
    procesamiento como FAILED.
    """

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], runner: AnalysisRunner, stale_after: float, clock: Callable[[], datetime]
    ) -> None:
        self._uow_factory = uow_factory
        self._runner = runner
        self._stale_after = timedelta(seconds=stale_after)
        self._clock = clock

    async def recover(self) -> int:
        async with self._uow_factory() as uow:
            stalled = await uow.analyses.list_stalled(self._clock() - self._stale_after)
        for analysis in stalled:
            self._runner.submit(analysis.id)
        if stalled:
            logger.info("Resumed %s stalled analyses", len(stalled))
        return len(stalled)
