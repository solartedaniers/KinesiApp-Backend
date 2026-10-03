import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChatRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatConversation(Base):
    """Hilo de chat de UN usuario sobre UN análisis: atleta, coach y admin tienen cada uno el suyo."""

    __tablename__ = "chat_conversations"
    __table_args__ = (UniqueConstraint("jump_analysis_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    jump_analysis_id: Mapped[int] = mapped_column(
        ForeignKey("jump_analyses.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        # Rate limit global (§6.7) e historial / rate limit por hilo
        Index("ix_chat_messages_created_at", "created_at"),
        Index("ix_chat_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, native_enum=False, length=10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Se fija en Python y no con now() de la base: el rate limit compara contra la hora de la app
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    # Sólo en respuestas del asistente: con qué versión del system prompt se generó
    system_prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")
