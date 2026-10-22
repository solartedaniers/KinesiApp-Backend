from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.repositories.async_base_repository import AsyncBaseRepository


class AsyncRefreshTokenRepository(AsyncBaseRepository[RefreshToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshToken)

    async def consume(self, token_hash: str) -> bool:
        # Revoco y compruebo en un solo UPDATE condicional: con dos renovaciones simultáneas solo una afecta la fila
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now)
            .values(revoked_at=now)
        )
        return result.rowcount == 1

    async def revoke_all_for_user(self, user_id: int) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
