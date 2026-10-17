from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.athlete import AthleteProfile
from app.models.jump_analysis import JumpAnalysis
from app.repositories.async_base_repository import AsyncBaseRepository


def _with_people() -> Select[tuple[AthleteProfile]]:
    # Cargo la cuenta y el coach de entrada: en async un acceso perezoso a display_name fallaría
    return select(AthleteProfile).options(selectinload(AthleteProfile.user), selectinload(AthleteProfile.coach))


class AsyncAthleteRepository(AsyncBaseRepository[AthleteProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AthleteProfile)

    async def count_by_coach(self, coach_id: int) -> int:
        return await self._session.scalar(
            select(func.count()).select_from(AthleteProfile).where(AthleteProfile.coach_id == coach_id)
        )

    async def get_profile(self, athlete_id: int) -> AthleteProfile | None:
        # populate_existing recarga las relaciones aunque la ficha ya esté en la sesión (recién creada o editada)
        query = _with_people().where(AthleteProfile.id == athlete_id).execution_options(populate_existing=True)
        return await self._session.scalar(query)

    async def get_by_user_id(self, user_id: int) -> AthleteProfile | None:
        return await self._session.scalar(_with_people().where(AthleteProfile.user_id == user_id))

    async def list_with_account_by_coach(self, coach_id: int) -> list[AthleteProfile]:
        query = _with_people().where(AthleteProfile.coach_id == coach_id, AthleteProfile.user_id.is_not(None))
        return list(await self._session.scalars(query.order_by(AthleteProfile.id)))

    async def list_managed_by_coach(self, coach_id: int) -> list[AthleteProfile]:
        query = _with_people().where(AthleteProfile.coach_id == coach_id, AthleteProfile.user_id.is_(None))
        return list(await self._session.scalars(query.order_by(AthleteProfile.id)))

    async def get_managed_by_coach(self, athlete_id: int, coach_id: int) -> AthleteProfile | None:
        query = _with_people().where(
            AthleteProfile.id == athlete_id, AthleteProfile.coach_id == coach_id, AthleteProfile.user_id.is_(None)
        )
        # Para borrarla, el ORM necesita sus análisis, sus mediciones y sus equipos ya cargados
        query = query.options(
            selectinload(AthleteProfile.jump_analyses).selectinload(JumpAnalysis.angle_measurements),
            selectinload(AthleteProfile.teams),
        )
        return await self._session.scalar(query.execution_options(populate_existing=True))

    async def list_after(self, after_id: int, limit: int) -> list[AthleteProfile]:
        query = _with_people().where(AthleteProfile.id > after_id).order_by(AthleteProfile.id).limit(limit)
        return list(await self._session.scalars(query))

    async def delete(self, athlete: AthleteProfile) -> None:
        await self._session.delete(athlete)
