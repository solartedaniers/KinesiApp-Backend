from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.models.chat import ChatRole


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=settings.CHAT_MESSAGE_MAX_CHARS)


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: ChatRole
    content: str
    created_at: datetime
