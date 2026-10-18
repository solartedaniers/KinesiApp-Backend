from collections.abc import Callable

from app.analysis.analysis_access import visible_analysis
from app.identity.principal import Principal
from app.models.chat import ChatMessage
from app.repositories.unit_of_work import UnitOfWork


class ConversationHistory:
    """Muestro el hilo de quien llama sobre un análisis: cada persona tiene el suyo y no ve el de otra."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def list(self, principal: Principal, analysis_id: int) -> list[ChatMessage]:
        async with self._uow_factory() as uow:
            await visible_analysis(uow, principal, analysis_id)
            conversation = await uow.conversations.find(analysis_id, principal.user_id)
            return await uow.messages.list_by_conversation(conversation.id) if conversation else []
