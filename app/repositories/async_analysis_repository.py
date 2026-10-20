from datetime import datetime

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.athlete import AthleteProfile
from app.models.chat import ChatConversation
from app.models.jump_analysis import JointAngleMeasurement, JumpAnalysis, JumpAnalysisStatus
from app.models.team import team_members
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

    async def find_by_video(self, video_reference: str) -> JumpAnalysis | None:
        return await self._session.scalar(_with_athlete().where(JumpAnalysis.video_reference == video_reference))

    async def claim(
        self, analysis_id: int, attempt_id: str, previous_attempt_id: str | None, now: datetime, lease_until: datetime
    ) -> bool:
        # Reclamo con un solo UPDATE condicional: si dos instancias lo intentan a la vez, la base deja ganar a una
        free = or_(JumpAnalysis.processing_lease_until.is_(None), JumpAnalysis.processing_lease_until < now)
        if previous_attempt_id is not None:
            free = or_(free, JumpAnalysis.processing_attempt_id == previous_attempt_id)
        return await self._take(
            and_(JumpAnalysis.id == analysis_id, JumpAnalysis.status == JumpAnalysisStatus.PENDING, free),
            processing_attempt_id=attempt_id, processing_lease_until=lease_until,
        )

    async def hold(self, analysis_id: int, attempt_id: str, lease_until: datetime) -> bool:
        # Renuevo el lease solo si el intento sigue siendo el dueño; el UPDATE además bloquea la fila hasta el commit
        owned = and_(
            JumpAnalysis.id == analysis_id,
            JumpAnalysis.status == JumpAnalysisStatus.PENDING,
            JumpAnalysis.processing_attempt_id == attempt_id,
        )
        return await self._take(owned, processing_lease_until=lease_until)

    async def list_recoverable(self, now: datetime, unclaimed_before: datetime) -> list[JumpAnalysis]:
        # Al que nadie reclamó todavía le doy un lease completo desde su último avance: lo tiene en cola quien lo confirmó
        abandoned = or_(
            JumpAnalysis.processing_lease_until < now,
            and_(JumpAnalysis.processing_lease_until.is_(None), JumpAnalysis.progress_updated_at < unclaimed_before),
        )
        query = select(JumpAnalysis).where(JumpAnalysis.status == JumpAnalysisStatus.PENDING, abandoned)
        return list(await self._session.scalars(query.order_by(JumpAnalysis.id)))

    async def count_pending(self) -> int:
        query = select(func.count()).select_from(JumpAnalysis).where(JumpAnalysis.status == JumpAnalysisStatus.PENDING)
        return await self._session.scalar(query)

    async def list_by_athlete(self, athlete_id: int, before_id: int, limit: int) -> list[JumpAnalysis]:
        return await self._newest_first(_with_athlete().where(JumpAnalysis.athlete_id == athlete_id), before_id, limit)

    async def list_by_coach(self, coach_id: int, before_id: int, limit: int, team_id: int | None = None) -> list[JumpAnalysis]:
        query = _with_athlete().join(JumpAnalysis.athlete).where(AthleteProfile.coach_id == coach_id)
        if team_id is not None:
            # Sigo exigiendo el coach: un deportista que cambió de entrenador puede seguir en un equipo viejo
            query = query.join(team_members, team_members.c.athlete_id == AthleteProfile.id).where(
                team_members.c.team_id == team_id
            )
        return await self._newest_first(query, before_id, limit)

    def add_measurements(self, measurements: list[JointAngleMeasurement]) -> None:
        # Las agrego sueltas y no por la relación: asignarla obligaría a cargar la colección vieja, y en async
        # no hay carga perezosa
        self._session.add_all(measurements)

    async def delete(self, analysis: JumpAnalysis) -> None:
        # Borro las conversaciones a mano: el ORM no las conoce desde el análisis y SQLite no aplica el
        # ON DELETE CASCADE sin activar las claves foráneas
        await self._session.execute(delete(ChatConversation).where(ChatConversation.jump_analysis_id == analysis.id))
        await self._session.refresh(analysis, ["angle_measurements"])
        await self._session.delete(analysis)

    async def _take(self, condition, **values: object) -> bool:
        statement = update(JumpAnalysis).where(condition).values(**values).execution_options(synchronize_session=False)
        return (await self._session.execute(statement)).rowcount == 1

    async def _newest_first(self, query: Select[tuple[JumpAnalysis]], before_id: int, limit: int) -> list[JumpAnalysis]:
        # El cursor es el último id que vio el cliente; con 0 empiezo por el más reciente
        if before_id:
            query = query.where(JumpAnalysis.id < before_id)
        return list(await self._session.scalars(query.order_by(JumpAnalysis.id.desc()).limit(limit)))
