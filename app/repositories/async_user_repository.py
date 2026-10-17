from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.async_base_repository import AsyncBaseRepository


class AsyncUserRepository(AsyncBaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def list_after(self, after_id: int, limit: int) -> list[User]:
        # Paginación por cursor sobre el id: estable aunque se creen cuentas mientras se recorre
        result = await self._session.scalars(select(User).where(User.id > after_id).order_by(User.id).limit(limit))
        return list(result)
