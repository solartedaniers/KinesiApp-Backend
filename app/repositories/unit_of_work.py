from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.async_analysis_repository import AsyncAnalysisRepository
from app.repositories.async_athlete_repository import AsyncAthleteRepository
from app.repositories.async_chat_repository import AsyncChatConversationRepository, AsyncChatMessageRepository
from app.repositories.async_refresh_token_repository import AsyncRefreshTokenRepository
from app.repositories.async_team_repository import AsyncTeamRepository
from app.repositories.async_user_repository import AsyncUserRepository


class UnitOfWork:
    """Abro una sesión y una transacción por caso de uso: los repositorios la comparten y commit confirma todo."""

    users: AsyncUserRepository
    refresh_tokens: AsyncRefreshTokenRepository
    athletes: AsyncAthleteRepository
    teams: AsyncTeamRepository
    analyses: AsyncAnalysisRepository
    conversations: AsyncChatConversationRepository
    messages: AsyncChatMessageRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.users = AsyncUserRepository(self._session)
        self.refresh_tokens = AsyncRefreshTokenRepository(self._session)
        self.athletes = AsyncAthleteRepository(self._session)
        self.teams = AsyncTeamRepository(self._session)
        self.analyses = AsyncAnalysisRepository(self._session)
        self.conversations = AsyncChatConversationRepository(self._session)
        self.messages = AsyncChatMessageRepository(self._session)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        # Descarto lo que no se confirmó con commit, también si el caso de uso falló a mitad.
        # Separo antes las instancias porque el rollback las expira y el caso de uso ya las devolvió
        self._session.expunge_all()
        await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()
