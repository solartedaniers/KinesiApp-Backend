from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatConversation, ChatMessage, ChatRole
from app.repositories.async_base_repository import AsyncBaseRepository


class AsyncChatConversationRepository(AsyncBaseRepository[ChatConversation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ChatConversation)

    async def find(self, analysis_id: int, user_id: int, *, lock: bool = False) -> ChatConversation | None:
        query = select(ChatConversation).where(
            ChatConversation.jump_analysis_id == analysis_id, ChatConversation.user_id == user_id
        )
        # Con lock serializo a dos pestañas del mismo usuario sobre el mismo hilo hasta el commit
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def get_or_create(self, analysis_id: int, user_id: int) -> ChatConversation:
        existing = await self.find(analysis_id, user_id)
        if existing is not None:
            return existing
        try:
            # El savepoint me deja seguir en la misma transacción si otra llamada creó el hilo primero
            async with self._session.begin_nested():
                conversation = ChatConversation(jump_analysis_id=analysis_id, user_id=user_id)
                self._session.add(conversation)
            return conversation
        except IntegrityError:
            winner = await self.find(analysis_id, user_id)
            if winner is None:
                raise
            return winner


class AsyncChatMessageRepository(AsyncBaseRepository[ChatMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ChatMessage)

    async def list_by_conversation(self, conversation_id: int) -> list[ChatMessage]:
        query = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.id)
        return list(await self._session.scalars(query))

    async def count_user_messages_since(self, since: datetime, conversation_id: int | None = None) -> int:
        query = select(func.count()).select_from(ChatMessage).where(
            ChatMessage.role == ChatRole.USER, ChatMessage.created_at >= since
        )
        if conversation_id is not None:
            query = query.where(ChatMessage.conversation_id == conversation_id)
        return await self._session.scalar(query)
