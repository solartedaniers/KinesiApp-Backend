from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes.jump_analyses import get_jump_analysis_service
from app.chat.llm import LlmClient
from app.chat.prompt_builder import JumpAnalysisPromptBuilder
from app.chat.rate_limiter import ChatRateLimiter
from app.chat.system_prompt import SYSTEM_PROMPT_VERSION
from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_roles
from app.models.user import User, UserRole
from app.repositories.chat_repository import ChatConversationRepository, ChatMessageRepository
from app.schemas.chat import ChatMessageCreate, ChatMessageRead
from app.services.chat_factory import get_llm_client, get_prompt_builder
from app.services.chat_service import ChatService
from app.services.jump_analysis_service import JumpAnalysisService

router = APIRouter(prefix="/jump-analyses", tags=["chat"])

# El chat es para quien entrena: el deportista y su coach. El admin administra, no conversa sobre análisis
_require_chat_user = require_roles(UserRole.ATHLETE, UserRole.COACH)


def _get_chat_service(
    db: Session = Depends(get_db),
    analyses: JumpAnalysisService = Depends(get_jump_analysis_service),
    prompt_builder: JumpAnalysisPromptBuilder = Depends(get_prompt_builder),
    llm_client: LlmClient = Depends(get_llm_client),
) -> ChatService:
    messages = ChatMessageRepository(db)
    return ChatService(
        analyses=analyses,
        conversations=ChatConversationRepository(db),
        messages=messages,
        rate_limiter=ChatRateLimiter(
            messages,
            per_conversation_per_hour=settings.CHAT_RATE_LIMIT_PER_USER_PER_HOUR,
            global_per_minute=settings.CHAT_RATE_LIMIT_GLOBAL_PER_MINUTE,
            now=lambda: datetime.now(timezone.utc),
        ),
        prompt_builder=prompt_builder,
        llm_client=llm_client,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
    )


@router.get("/{analysis_id}/chat/messages", response_model=list[ChatMessageRead])
def list_chat_messages(
    analysis_id: int,
    current_user: User = Depends(_require_chat_user),
    service: ChatService = Depends(_get_chat_service),
) -> list[ChatMessageRead]:
    return service.list_messages(current_user, analysis_id)


@router.post("/{analysis_id}/chat/opening", response_model=list[ChatMessageRead])
def start_chat(
    analysis_id: int,
    current_user: User = Depends(_require_chat_user),
    service: ChatService = Depends(_get_chat_service),
) -> list[ChatMessageRead]:
    # Idempotente: la pantalla del análisis lo pide al mostrarse y sólo la primera vez llama a Gemini
    return service.start_conversation(current_user, analysis_id)


@router.post("/{analysis_id}/chat/messages", response_model=ChatMessageRead)
def send_chat_message(
    analysis_id: int,
    data: ChatMessageCreate,
    current_user: User = Depends(_require_chat_user),
    service: ChatService = Depends(_get_chat_service),
) -> ChatMessageRead:
    # `def`: la llamada a Gemini es bloqueante y corre en el threadpool, no en el event loop
    return service.send_message(current_user, analysis_id, data.content)
