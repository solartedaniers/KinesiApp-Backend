from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.chat import ChatConversation, ChatMessage, ChatRole
from app.repositories.base_repository import BaseRepository


class ChatConversationRepository(BaseRepository[ChatConversation]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, ChatConversation)

    def find(self, jump_analysis_id: int, user_id: int) -> ChatConversation | None:
        return self._db.scalar(
            select(ChatConversation).where(
                ChatConversation.jump_analysis_id == jump_analysis_id, ChatConversation.user_id == user_id
            )
        )

    def get_or_create(self, jump_analysis_id: int, user_id: int) -> ChatConversation:
        existing = self.find(jump_analysis_id, user_id)
        if existing is not None:
            return existing
        try:
            return self.add(ChatConversation(jump_analysis_id=jump_analysis_id, user_id=user_id))
        except IntegrityError:
            # Otro request simultáneo del mismo usuario creó el hilo primero: se usa ése
            self._db.rollback()
            winner = self.find(jump_analysis_id, user_id)
            if winner is None:
                raise
            return winner


class ChatMessageRepository(BaseRepository[ChatMessage]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, ChatMessage)

    def list_by_conversation(self, conversation_id: int) -> list[ChatMessage]:
        return list(
            self._db.scalars(
                select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.id)
            )
        )

    def count_user_messages_since(self, since: datetime, conversation_id: int | None = None) -> int:
        query = select(func.count()).select_from(ChatMessage).where(
            ChatMessage.role == ChatRole.USER, ChatMessage.created_at >= since
        )
        if conversation_id is not None:
            query = query.where(ChatMessage.conversation_id == conversation_id)
        return self._db.scalar(query)
