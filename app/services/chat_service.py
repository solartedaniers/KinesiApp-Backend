import logging

from kinesiapp_ai.chat.llm import LlmClient, LlmRequest, LlmUnavailableError
from kinesiapp_ai.chat.prompt_builder import JumpAnalysisPromptBuilder

from app.chat.rate_limiter import ChatRateLimitedError, ChatRateLimiter
from app.core.exceptions import ConflictException, ErrorCode, ServiceUnavailableException, TooManyRequestsException
from app.models.chat import ChatMessage, ChatRole
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus
from app.models.user import User
from app.repositories.chat_repository import ChatConversationRepository, ChatMessageRepository
from app.services.chat_prompt_mapper import to_analysis_prompt_input, to_history_messages
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

    def start_conversation(self, current_user: User, analysis_id: int) -> list[ChatMessage]:
        """Hilo con la explicación inicial del resultado, generada la primera vez que se pide.

        Idempotente: si el hilo ya tiene mensajes, los devuelve sin llamar al proveedor. Lo pide la
        pantalla del análisis en cuanto el resultado está listo.
        """
        analysis = self._processed_analysis(current_user, analysis_id)
        conversation = self._conversations.get_or_create(analysis_id, current_user.id)
        existing = self._messages.list_by_conversation(conversation.id)
        if existing:
            return existing
        self._check_rate_limit(conversation.id)
        request = self._prompt_builder.build_opening(to_analysis_prompt_input(analysis), current_user.role.value)
        reply = self._generate(request, analysis_id)
        # Mientras se esperaba al proveedor, otra pestaña del mismo usuario pudo abrir el hilo
        existing = self._messages.list_by_conversation(conversation.id)
        if existing:
            return existing
        return [self._add_reply(conversation.id, reply)]

    def send_message(self, current_user: User, analysis_id: int, content: str) -> ChatMessage:
        analysis = self._processed_analysis(current_user, analysis_id)
        conversation = self._conversations.get_or_create(analysis_id, current_user.id)
        self._check_rate_limit(conversation.id)

        history = self._messages.list_by_conversation(conversation.id)
        # Se guarda antes de llamar al proveedor: cuenta para el rate limit aunque la llamada falle
        self._messages.add(ChatMessage(conversation_id=conversation.id, role=ChatRole.USER, content=content))
        request = self._prompt_builder.build(
            to_analysis_prompt_input(analysis), current_user.role.value, to_history_messages(history), content
        )
        return self._add_reply(conversation.id, self._generate(request, analysis_id))

    def _processed_analysis(self, current_user: User, analysis_id: int) -> JumpAnalysis:
        analysis = self._analyses.get_analysis(current_user, analysis_id)
        if analysis.status != JumpAnalysisStatus.PROCESSED:
            raise ConflictException("The analysis has not been processed", code=ErrorCode.ANALYSIS_NOT_PROCESSED)
        return analysis

    def _check_rate_limit(self, conversation_id: int) -> None:
        try:
            self._rate_limiter.check(conversation_id)
        except ChatRateLimitedError as error:
            raise TooManyRequestsException(str(error), code=ErrorCode.CHAT_RATE_LIMITED) from error

    def _generate(self, request: LlmRequest, analysis_id: int) -> str:
        try:
            return self._llm_client.generate_reply(request)
        except LlmUnavailableError as error:
            logger.warning("Chat assistant unavailable for analysis %s: %s", analysis_id, error)
            raise ServiceUnavailableException(
                "The assistant is not available right now", code=ErrorCode.ASSISTANT_UNAVAILABLE
            ) from error

    def _add_reply(self, conversation_id: int, reply: str) -> ChatMessage:
        return self._messages.add(
            ChatMessage(
                conversation_id=conversation_id,
                role=ChatRole.ASSISTANT,
                content=reply,
                system_prompt_version=self._system_prompt_version,
            )
        )
