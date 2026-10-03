"""Add chat_conversations and chat_messages (one thread per analysis and user).

Revision ID: 3b8fa7cd75a7
Revises: d4b9f2a7c615
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3b8fa7cd75a7"
down_revision: Union[str, None] = "d4b9f2a7c615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("jump_analysis_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["jump_analysis_id"], ["jump_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jump_analysis_id", "user_id"),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Enum("USER", "ASSISTANT", name="chatrole", native_enum=False, length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_prompt_version", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])
    op.create_index("ix_chat_messages_conversation_id_created_at", "chat_messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
