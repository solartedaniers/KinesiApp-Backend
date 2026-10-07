from kinesiapp_ai.chat.prompt_builder import AnalysisPromptInput, HistoryMessage

from app.models.chat import ChatMessage
from app.models.jump_analysis import JumpAnalysis


def to_analysis_prompt_input(analysis: JumpAnalysis) -> AnalysisPromptInput:
    """Sólo los datos estructurados del resultado: el paquete de IA nunca ve el ORM ni datos personales."""
    return AnalysisPromptInput(
        movement=analysis.movement_type.value,
        risk_score=analysis.risk_score,
        dominant_risk_pattern=analysis.dominant_risk_pattern,
        risk_details=analysis.risk_details,
    )


def to_history_messages(messages: list[ChatMessage]) -> list[HistoryMessage]:
    return [HistoryMessage(role=message.role.value, content=message.content) for message in messages]
