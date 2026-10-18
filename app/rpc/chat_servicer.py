from collections.abc import AsyncIterator

import grpc
from kinesiapp.chat.v1 import chat_pb2, chat_pb2_grpc
from kinesiapp.common.v1 import chat_pb2 as common_chat_pb2

from app.analysis.inputs import AnalysisIdInput
from app.chat.chat_events import SavedMessage, TextDelta
from app.chat.conversation_history import ConversationHistory
from app.chat.conversation_opening import ConversationOpening
from app.chat.inputs import ChatInputRules, QuestionInput
from app.chat.question_answering import QuestionAnswering
from app.identity.principal import current_principal
from app.models.chat import ChatMessage, ChatRole
from app.rpc.proto_values import timestamp

_ROLES = {ChatRole.USER: common_chat_pb2.CHAT_ROLE_USER, ChatRole.ASSISTANT: common_chat_pb2.CHAT_ROLE_ASSISTANT}


class ChatServicer(chat_pb2_grpc.ChatServiceServicer):
    """Implemento kinesiapp.chat.v1.ChatService; el contrato ya lo restringe a ATHLETE y COACH."""

    def __init__(
        self,
        rules: ChatInputRules,
        history: ConversationHistory,
        opening: ConversationOpening,
        answering: QuestionAnswering,
    ) -> None:
        self._rules = rules
        self._history = history
        self._opening = opening
        self._answering = answering

    async def ListMessages(
        self, request: chat_pb2.ListMessagesRequest, context: grpc.aio.ServicerContext
    ) -> chat_pb2.ListMessagesResponse:
        data = AnalysisIdInput.model_validate({"analysis_id": request.analysis_id})
        messages = await self._history.list(current_principal(), data.analysis_id)
        return chat_pb2.ListMessagesResponse(messages=[_message(message) for message in messages])

    async def StartConversation(
        self, request: chat_pb2.StartConversationRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[chat_pb2.StartConversationResponse]:
        data = AnalysisIdInput.model_validate({"analysis_id": request.analysis_id})
        async for event in self._opening.open(current_principal(), data.analysis_id):
            if isinstance(event, TextDelta):
                yield chat_pb2.StartConversationResponse(text_delta=event.text)
            else:
                yield chat_pb2.StartConversationResponse(assistant_message=_message(event.message))

    async def SendMessage(
        self, request: chat_pb2.SendMessageRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[chat_pb2.SendMessageResponse]:
        data = self._rules.parse(QuestionInput, {"analysis_id": request.analysis_id, "content": request.content})
        async for event in self._answering.ask(current_principal(), data.analysis_id, data.content):
            yield _send_event(event)


def _send_event(event: TextDelta | SavedMessage) -> chat_pb2.SendMessageResponse:
    if isinstance(event, TextDelta):
        return chat_pb2.SendMessageResponse(text_delta=event.text)
    if event.message.role == ChatRole.USER:
        return chat_pb2.SendMessageResponse(user_message=_message(event.message))
    return chat_pb2.SendMessageResponse(assistant_message=_message(event.message))


def _message(message: ChatMessage) -> chat_pb2.ChatMessage:
    return chat_pb2.ChatMessage(
        id=message.id, role=_ROLES[message.role], content=message.content, created_at=timestamp(message.created_at)
    )
