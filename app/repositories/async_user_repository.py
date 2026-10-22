from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.async_base_repository import AsyncBaseRepository


class AsyncUserRepository(AsyncBaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def list_after(self, after_id: int, limit: int) -> list[User]:
        # Pagino por cursor sobre el id: es estable aunque se creen cuentas mientras se recorre
        result = await self._session.scalars(select(User).where(User.id > after_id).order_by(User.id).limit(limit))
        return list(result)

    async def take_code_attempt(self, user_id: int, attempts_column: str, max_attempts: int) -> bool:
        # Sumo el intento en un solo UPDATE condicional: con peticiones simultáneas el contador no pasa del máximo
        attempts = getattr(User, attempts_column)
        result = await self._session.execute(
            update(User).where(User.id == user_id, attempts < max_attempts).values({attempts: attempts + 1})
        )
        return result.rowcount == 1
