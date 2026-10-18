from dataclasses import dataclass

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.ai.remote_assistant import AssistantReply
from app.analysis.analysis_access import visible_analysis
from app.core.domain_error import DomainError
from app.identity.principal import Principal
from app.models.chat import ChatMessage, ChatRole
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus
from app.repositories.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class SavedMessage:
    message: ChatMessage


ChatEvent = TextDelta | SavedMessage


async def processed_analysis(uow: UnitOfWork, principal: Principal, analysis_id: int) -> JumpAnalysis:
    analysis = await visible_analysis(uow, principal, analysis_id)
    if analysis.status != JumpAnalysisStatus.PROCESSED:
        raise DomainError(ErrorReason.ERROR_REASON_ANALYSIS_NOT_PROCESSED, "The analysis has not been processed")
    return analysis


def assistant_message(conversation_id: int, reply: AssistantReply) -> ChatMessage:
    return ChatMessage(
        conversation_id=conversation_id,
        role=ChatRole.ASSISTANT,
        content=reply.content,
        system_prompt_version=reply.prompt_version,
    )
