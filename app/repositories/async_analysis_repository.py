from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.athlete import AthleteProfile
from app.models.chat import ChatConversation
from app.models.jump_analysis import JumpAnalysis
from app.repositories.async_base_repository import AsyncBaseRepository


def _with_athlete() -> Select[tuple[JumpAnalysis]]:
    # Cargo el deportista de entrada: los permisos dependen de él y en async no puedo leerlo perezoso
    return select(JumpAnalysis).options(selectinload(JumpAnalysis.athlete))


class AsyncAnalysisRepository(AsyncBaseRepository[JumpAnalysis]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, JumpAnalysis)

    async def get_with_athlete(self, analysis_id: int) -> JumpAnalysis | None:
        query = _with_athlete().where(JumpAnalysis.id == analysis_id).execution_options(populate_existing=True)
        return await self._session.scalar(query)

    async def get_with_measurements(self, analysis_id: int) -> JumpAnalysis | None:
        query = _with_athlete().options(selectinload(JumpAnalysis.angle_measurements))
        return await self._session.scalar(query.where(JumpAnalysis.id == analysis_id))

    async def list_by_athlete(self, athlete_id: int, before_id: int, limit: int) -> list[JumpAnalysis]:
        return await self._newest_first(_with_athlete().where(JumpAnalysis.athlete_id == athlete_id), before_id, limit)

    async def list_by_coach(self, coach_id: int, before_id: int, limit: int) -> list[JumpAnalysis]:
        query = _with_athlete().join(JumpAnalysis.athlete).where(AthleteProfile.coach_id == coach_id)
        return await self._newest_first(query, before_id, limit)

    async def delete(self, analysis: JumpAnalysis) -> None:
        # Borro las conversaciones a mano: el ORM no las conoce desde el análisis y SQLite no aplica el
        # ON DELETE CASCADE sin activar las claves foráneas
        await self._session.execute(delete(ChatConversation).where(ChatConversation.jump_analysis_id == analysis.id))
        await self._session.refresh(analysis, ["angle_measurements"])
        await self._session.delete(analysis)

    async def _newest_first(self, query: Select[tuple[JumpAnalysis]], before_id: int, limit: int) -> list[JumpAnalysis]:
        # El cursor es el último id que vio el cliente; con 0 empiezo por el más reciente
        if before_id:
            query = query.where(JumpAnalysis.id < before_id)
        return list(await self._session.scalars(query.order_by(JumpAnalysis.id.desc()).limit(limit)))
