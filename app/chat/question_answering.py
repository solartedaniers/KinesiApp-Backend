from collections.abc import AsyncIterator, Callable

from app.ai.remote_assistant import AnalysisAssistant, AssistantReply
from app.chat.analysis_facts import AnalysisFactsBuilder
from app.chat.chat_events import ChatEvent, SavedMessage, TextDelta, assistant_message, processed_analysis
from app.chat.usage_limits import ChatUsageLimits
from app.identity.principal import Principal
from app.models.chat import ChatMessage, ChatRole
from app.repositories.unit_of_work import UnitOfWork


class QuestionAnswering:
    """Guardo la pregunta, pido la respuesta a la IA en streaming y la guardo.

    Guardo la pregunta antes de llamar a la IA: si la IA falla, igual cuenta para el límite y así nadie
    lo esquiva provocando fallos. Si el usuario reintenta la misma pregunta que quedó sin respuesta, la reutilizo:
    no la guardo dos veces ni la cuento otra vez.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        facts: AnalysisFactsBuilder,
        assistant: AnalysisAssistant,
        limits: ChatUsageLimits,
    ) -> None:
        self._uow_factory = uow_factory
        self._facts = facts
        self._assistant = assistant
        self._limits = limits

    async def ask(self, principal: Principal, analysis_id: int, question: str) -> AsyncIterator[ChatEvent]:
        async with self._uow_factory() as uow:
            analysis = await processed_analysis(uow, principal, analysis_id)
            conversation = await uow.conversations.get_or_create(analysis_id, principal.user_id)
            await uow.commit()
        async with self._uow_factory() as uow:
            # Bloqueo el hilo para contar y guardar de una vez: dos preguntas simultáneas no pasan el tope juntas
            await uow.conversations.lock(analysis_id, principal.user_id)
            history = await uow.messages.list_by_conversation(conversation.id)
            if history and history[-1].role == ChatRole.USER and history[-1].content == question:
                asked, history = history[-1], history[:-1]
            else:
                await self._limits.check(uow, conversation.id)
                asked = ChatMessage(conversation_id=conversation.id, role=ChatRole.USER, content=question)
                uow.messages.add(asked)
            await uow.commit()
        yield SavedMessage(asked)
        reply = None
        async for event in self._assistant.answer(self._facts.build(analysis), principal.role, history, question):
            if isinstance(event, AssistantReply):
                reply = event
            else:
                yield TextDelta(event)
        async with self._uow_factory() as uow:
            answered = assistant_message(conversation.id, reply)
            uow.messages.add(answered)
            await uow.commit()
        yield SavedMessage(answered)
