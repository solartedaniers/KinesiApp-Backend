from collections.abc import AsyncIterator, Callable

from app.analysis.analysis_access import visible_analysis
from app.analysis.progress import AnalysisFinished, AnalysisProgressUpdate
from app.analysis.progress_hub import AnalysisProgressHub
from app.identity.principal import Principal
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus
from app.repositories.unit_of_work import UnitOfWork

# Cada evento es un avance o, al final, el análisis ya terminado
WatchEvent = AnalysisProgressUpdate | JumpAnalysis


class AnalysisWatch:
    """Sigo un análisis: primero lo persistido y luego lo que publica el procesamiento, hasta que termina."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], hub: AnalysisProgressHub) -> None:
        self._uow_factory = uow_factory
        self._hub = hub

    async def watch(self, principal: Principal, analysis_id: int) -> AsyncIterator[WatchEvent]:
        # Me suscribo antes de leer la base: si el análisis termina entre las dos cosas, el aviso no se pierde
        with self._hub.subscribe(analysis_id) as subscription:
            analysis = await self._load(principal, analysis_id)
            if analysis.status is not JumpAnalysisStatus.PENDING:
                yield analysis
                return
            yield AnalysisProgressUpdate(analysis.stage, analysis.frames_processed, analysis.frames_total)
            async for event in subscription.events():
                if isinstance(event, AnalysisFinished):
                    # Lo releo: también me avisan cuando lo borran, y entonces respondo NOT_FOUND
                    yield await self._load(principal, analysis_id)
                    return
                yield event

    async def _load(self, principal: Principal, analysis_id: int) -> JumpAnalysis:
        async with self._uow_factory() as uow:
            return await visible_analysis(uow, principal, analysis_id)
