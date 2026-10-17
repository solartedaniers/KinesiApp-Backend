from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.athlete import AthleteProfile
from app.repositories.async_base_repository import AsyncBaseRepository


class AsyncAthleteRepository(AsyncBaseRepository[AthleteProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AthleteProfile)

    async def count_by_coach(self, coach_id: int) -> int:
        return await self._session.scalar(
            select(func.count()).select_from(AthleteProfile).where(AthleteProfile.coach_id == coach_id)
        )
