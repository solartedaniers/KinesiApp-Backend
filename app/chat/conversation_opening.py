from collections.abc import AsyncIterator, Callable

from app.ai.remote_assistant import AnalysisAssistant, AssistantReply
from app.chat.analysis_facts import AnalysisFactsBuilder
from app.chat.chat_events import ChatEvent, SavedMessage, TextDelta, assistant_message, processed_analysis
from app.chat.usage_limits import ChatUsageLimits
from app.identity.principal import Principal
from app.models.chat import ChatMessage
from app.repositories.unit_of_work import UnitOfWork


class ConversationOpening:
    """Genero la primera explicación de un análisis procesado. Es idempotente: la segunda vez emito la guardada.

    No bloqueo el hilo mientras espero a la IA para no tener una transacción abierta durante segundos.
    Si dos pestañas abren a la vez, las dos generan, pero al guardar reviso con el hilo bloqueado y solo
    queda la primera; la otra recibe esa misma explicación como mensaje final.
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

    async def open(self, principal: Principal, analysis_id: int) -> AsyncIterator[ChatEvent]:
        async with self._uow_factory() as uow:
            analysis = await processed_analysis(uow, principal, analysis_id)
            conversation = await uow.conversations.get_or_create(analysis_id, principal.user_id)
            existing = await uow.messages.list_by_conversation(conversation.id)
            if not existing:
                await self._limits.check(uow, conversation.id)
            await uow.commit()
        if existing:
            yield SavedMessage(existing[0])
            return
        reply = None
        async for event in self._assistant.explain(self._facts.build(analysis), principal.role):
            if isinstance(event, AssistantReply):
                reply = event
            else:
                yield TextDelta(event)
        yield SavedMessage(await self._save_first(principal, analysis_id, reply))

    async def _save_first(self, principal: Principal, analysis_id: int, reply: AssistantReply) -> ChatMessage:
        async with self._uow_factory() as uow:
            await uow.conversations.lock(analysis_id, principal.user_id)
            conversation = await uow.conversations.find(analysis_id, principal.user_id)
            existing = await uow.messages.list_by_conversation(conversation.id)
            if existing:
                return existing[0]
            message = assistant_message(conversation.id, reply)
            uow.messages.add(message)
            await uow.commit()
            return message
