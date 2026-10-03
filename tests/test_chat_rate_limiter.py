"""ChatRateLimiter: cuenta mensajes de usuario guardados, por hilo y global."""
from datetime import datetime, timedelta, timezone

import pytest

from app.chat.rate_limiter import ChatRateLimitedError, ChatRateLimiter
from app.models.chat import ChatConversation, ChatMessage, ChatRole
from app.models.jump_analysis import JumpAnalysis
from app.repositories.chat_repository import ChatMessageRepository

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _conversation(db, user_id: int) -> int:
    analysis = JumpAnalysis(athlete_id=1, video_reference="v.mp4")
    db.add(analysis)
    db.flush()
    conversation = ChatConversation(jump_analysis_id=analysis.id, user_id=user_id)
    db.add(conversation)
    db.commit()
    return conversation.id


def _messages(db, conversation_id: int, count: int, age: timedelta, role=ChatRole.USER) -> None:
    db.add_all(
        ChatMessage(conversation_id=conversation_id, role=role, content="x", created_at=NOW - age) for _ in range(count)
    )
    db.commit()


def _limiter(db, per_hour: int = 3, per_minute: int = 100) -> ChatRateLimiter:
    return ChatRateLimiter(ChatMessageRepository(db), per_hour, per_minute, now=lambda: NOW)


def test_conversation_limit_counts_only_user_messages_in_the_last_hour(db_session):
    conversation = _conversation(db_session, user_id=1)
    _messages(db_session, conversation, 2, timedelta(minutes=30))
    _messages(db_session, conversation, 5, timedelta(minutes=30), role=ChatRole.ASSISTANT)
    _messages(db_session, conversation, 5, timedelta(hours=2))
    _limiter(db_session).check(conversation)

    _messages(db_session, conversation, 1, timedelta(minutes=1))
    with pytest.raises(ChatRateLimitedError):
        _limiter(db_session).check(conversation)


def test_each_thread_has_its_own_quota(db_session):
    athlete_thread, coach_thread = _conversation(db_session, user_id=1), _conversation(db_session, user_id=2)
    _messages(db_session, athlete_thread, 3, timedelta(minutes=5))
    with pytest.raises(ChatRateLimitedError):
        _limiter(db_session).check(athlete_thread)
    _limiter(db_session).check(coach_thread)


def test_global_limit_counts_every_thread_in_the_last_minute(db_session):
    first, second = _conversation(db_session, user_id=1), _conversation(db_session, user_id=2)
    _messages(db_session, first, 1, timedelta(seconds=10))
    _messages(db_session, second, 1, timedelta(seconds=20))
    _messages(db_session, second, 5, timedelta(minutes=2))
    with pytest.raises(ChatRateLimitedError):
        _limiter(db_session, per_hour=100, per_minute=2).check(first)
    _limiter(db_session, per_hour=100, per_minute=3).check(first)
