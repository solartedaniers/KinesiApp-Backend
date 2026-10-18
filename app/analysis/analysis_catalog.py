from collections.abc import Callable
from dataclasses import dataclass

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.analysis.analysis_access import can_see, visible_analysis
from app.athletes.profile_records import existing_athlete
from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.jump_analysis import JumpAnalysis
from app.repositories.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class AnalysisPage:
    analyses: list[JumpAnalysis]
    # Lo dejo en None cuando no quedan más análisis después de esta página
    last_id: int | None


class AnalysisCatalog:
    """Muestro un análisis completo o los listados, del más reciente al más antiguo, a quien puede verlos."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def get(self, principal: Principal, analysis_id: int) -> JumpAnalysis:
        async with self._uow_factory() as uow:
            return await visible_analysis(uow, principal, analysis_id, with_measurements=True)

    async def list_for_athlete(self, principal: Principal, athlete_id: int, before_id: int, limit: int) -> AnalysisPage:
        async with self._uow_factory() as uow:
            athlete = await existing_athlete(uow, athlete_id)
            if not can_see(principal, athlete):
                raise DomainError(ErrorReason.ERROR_REASON_FORBIDDEN, "You cannot see this athlete's analyses")
            # Pido uno de más para saber si hay otra página sin contar toda la tabla
            return _page(await uow.analyses.list_by_athlete(athlete_id, before_id, limit + 1), limit)

    async def list_coached(self, principal: Principal, before_id: int, limit: int) -> AnalysisPage:
        async with self._uow_factory() as uow:
            return _page(await uow.analyses.list_by_coach(principal.user_id, before_id, limit + 1), limit)


def _page(analyses: list[JumpAnalysis], limit: int) -> AnalysisPage:
    has_more = len(analyses) > limit
    analyses = analyses[:limit]
    return AnalysisPage(analyses, analyses[-1].id if has_more else None)
