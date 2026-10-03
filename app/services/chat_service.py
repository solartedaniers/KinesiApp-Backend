import logging

from app.chat.llm import LlmClient, LlmUnavailableError
from app.chat.prompt_builder import JumpAnalysisPromptBuilder
from app.chat.rate_limiter import ChatRateLimitedError, ChatRateLimiter
from app.core.exceptions import ConflictException, ErrorCode, ServiceUnavailableException, TooManyRequestsException
from app.models.chat import ChatMessage, ChatRole
from app.models.jump_analysis import JumpAnalysisStatus
from app.models.user import User
from app.repositories.chat_repository import ChatConversationRepository, ChatMessageRepository
from app.services.jump_analysis_service import JumpAnalysisService

logger = logging.getLogger(__name__)


class ChatService:
    """Chat de un usuario sobre un análisis: autoriza, limita, arma el prompt y guarda el hilo.

    Cada usuario opera sólo sobre su propio hilo (jump_analysis_id, current_user.id): el coach no
    ve lo que el atleta le preguntó al asistente, ni al revés (§6.6).
    """

    def __init__(
        self,
        analyses: JumpAnalysisService,
        conversations: ChatConversationRepository,
        messages: ChatMessageRepository,
        rate_limiter: ChatRateLimiter,
        prompt_builder: JumpAnalysisPromptBuilder,
        llm_client: LlmClient,
        system_prompt_version: str,
    ) -> None:
        self._analyses = analyses
        self._conversations = conversations
        self._messages = messages
        self._rate_limiter = rate_limiter
        self._prompt_builder = prompt_builder
        self._llm_client = llm_client
        self._system_prompt_version = system_prompt_version

    def list_messages(self, current_user: User, analysis_id: int) -> list[ChatMessage]:
        self._analyses.get_analysis(current_user, analysis_id)
        conversation = self._conversations.find(analysis_id, current_user.id)
        return self._messages.list_by_conversation(conversation.id) if conversation else []

    def send_message(self, current_user: User, analysis_id: int, content: str) -> ChatMessage:
        analysis = self._analyses.get_analysis(current_user, analysis_id)
        if analysis.status != JumpAnalysisStatus.PROCESSED:
            raise ConflictException("The analysis has not been processed", code=ErrorCode.ANALYSIS_NOT_PROCESSED)
        conversation = self._conversations.get_or_create(analysis_id, current_user.id)
        try:
            self._rate_limiter.check(conversation.id)
        except ChatRateLimitedError as error:
            raise TooManyRequestsException(str(error), code=ErrorCode.CHAT_RATE_LIMITED) from error

        history = self._messages.list_by_conversation(conversation.id)
        # Se guarda antes de llamar al proveedor: cuenta para el rate limit aunque la llamada falle
        self._messages.add(ChatMessage(conversation_id=conversation.id, role=ChatRole.USER, content=content))
        request = self._prompt_builder.build(analysis, current_user.role, history, content)
        try:
            reply = self._llm_client.generate_reply(request)
        except LlmUnavailableError as error:
            logger.warning("Chat assistant unavailable for analysis %s: %s", analysis_id, error)
            raise ServiceUnavailableException(
                "The assistant is not available right now", code=ErrorCode.ASSISTANT_UNAVAILABLE
            ) from error
        return self._messages.add(
            ChatMessage(
                conversation_id=conversation.id,
                role=ChatRole.ASSISTANT,
                content=reply,
                system_prompt_version=self._system_prompt_version,
            )
        )
