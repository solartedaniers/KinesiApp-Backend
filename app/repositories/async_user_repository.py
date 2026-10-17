from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.async_base_repository import AsyncBaseRepository


class AsyncUserRepository(AsyncBaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)
