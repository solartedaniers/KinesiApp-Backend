"""Pruebo ChatService por la red: permisos, streaming, idempotencia, límites, fallos de la IA y carreras."""

import asyncio
import json
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path

import grpc
import pytest
from kinesiapp.chat.v1 import chat_pb2, chat_pb2_grpc
from kinesiapp.common.v1 import chat_pb2 as common_chat_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from sqlalchemy import select

from app.ai.remote_assistant import AssistantReply
from app.analysis.risk_assessment_codec import RiskAssessmentCodec
from app.analysis.risk_level import RiskLevelClassifier
from app.chat.analysis_facts import AnalysisFactsBuilder
from app.chat.conversation_history import ConversationHistory
from app.chat.conversation_opening import ConversationOpening
from app.chat.inputs import ChatInputRules
from app.chat.question_answering import QuestionAnswering
from app.chat.usage_limits import ChatUsageLimits
from app.core.domain_error import DomainError
from app.models.athlete import AthleteProfile, Gender
from app.models.chat import ChatMessage, ChatRole
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus, MovementType
from app.models.user import UserRole
from app.rpc.chat_servicer import ChatServicer
from tests.grpc_harness import error_info, field_violations
from tests.rpc_world import World, bearer, rpc_world, uow_factory

SAMPLE = json.loads((Path(__file__).parent / "risk_details_sample.json").read_text(encoding="utf-8"))
MAX_CHARS = 20


class _FakeAssistant:
    """Asistente en memoria: cuenta las llamadas, puede tardar y puede fallar a mitad de la respuesta."""

    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.explained = 0
        self.questions: list[tuple[list[str], str]] = []

    async def explain(self, facts, audience):
        self.explained += 1
        self.last_facts = facts
        async for event in self._reply(f"Explicación para {audience.value}"):
            yield event

    async def answer(self, facts, audience, history, question):
        self.questions.append(([message.content for message in history], question))
        async for event in self._reply(f"Respuesta a {question}"):
            yield event

    async def _reply(self, text: str):
        half = len(text) // 2
        yield text[:half]
        await asyncio.sleep(self.delay)
        if self.fail:
            raise DomainError(ErrorReason.ERROR_REASON_ASSISTANT_UNAVAILABLE, "down")
        yield text[half:]
        yield AssistantReply(text, "prompt-v9")


def _run(tmp_path: Path, scenario, assistant: _FakeAssistant | None = None, per_hour: int = 20, per_minute: int = 50):
    assistant = assistant or _FakeAssistant()

    def register(session_factory):
        uows = uow_factory(session_factory)
        facts = AnalysisFactsBuilder(RiskAssessmentCodec(), RiskLevelClassifier(0.33, 0.66))
        limits = ChatUsageLimits(per_hour, per_minute, lambda: datetime.now(timezone.utc))
        servicer = ChatServicer(
            ChatInputRules(MAX_CHARS),
            ConversationHistory(uows),
            ConversationOpening(uows, facts, assistant, limits),
            QuestionAnswering(uows, facts, assistant, limits),
        )
        return partial(chat_pb2_grpc.add_ChatServiceServicer_to_server, servicer)

    async def main():
        async with rpc_world(tmp_path / "chat.db", register) as world:
            return await scenario(world, chat_pb2_grpc.ChatServiceStub(world.channel), assistant)

    return asyncio.run(main())


async def _people(world: World, status: JumpAnalysisStatus = JumpAnalysisStatus.PROCESSED):
    coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
    athlete = await world.user("atleta@kinesiapp.com", UserRole.ATHLETE)
    stranger = await world.user("otro@kinesiapp.com", UserRole.ATHLETE)
    async with world.session_factory() as session:
        profile = AthleteProfile(
            user_id=athlete.id, coach_id=coach.id, gender=Gender.FEMALE, height_cm=165, weight_kg=60, birth_date=date(2002, 5, 6)
        )
        session.add(profile)
        await session.flush()
        analysis = JumpAnalysis(
            athlete_id=profile.id,
            video_reference="https://bucket.test/videos/a.mp4",
            movement_type=MovementType.JUMP,
            status=status,
            risk_score=1.0,
            dominant_risk_pattern="forward_collapse",
            risk_details=SAMPLE,
        )
        session.add(analysis)
        await session.commit()
        return coach, athlete, stranger, analysis.id


async def _stream(call) -> tuple[list, grpc.aio.AioRpcError | None]:
    received = []
    try:
        async for reply in call:
            received.append(reply)
    except grpc.aio.AioRpcError as error:
        return received, error
    return received, None


async def _messages(world: World) -> list[tuple[ChatRole, str]]:
    async with world.session_factory() as session:
        return [(m.role, m.content) for m in await session.scalars(select(ChatMessage).order_by(ChatMessage.id))]


def test_the_opening_streams_the_explanation_and_the_second_time_returns_the_saved_one(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, _, analysis_id = await _people(world)
        request = chat_pb2.StartConversationRequest(analysis_id=analysis_id)
        first, _ = await _stream(stub.StartConversation(request, metadata=bearer(athlete)))
        again, _ = await _stream(stub.StartConversation(request, metadata=bearer(athlete)))
        return first, again, assistant

    first, again, assistant = _run(tmp_path, scenario)

    deltas = [reply.text_delta for reply in first if reply.HasField("text_delta")]
    final = first[-1].assistant_message
    assert "".join(deltas) == final.content == "Explicación para athlete"
    assert final.role == common_chat_pb2.CHAT_ROLE_ASSISTANT
    assert [reply.assistant_message.id for reply in again] == [final.id]
    assert assistant.explained == 1
    # El asistente recibe el desglose de riesgo con el nivel que corresponde a sus cortes
    assert assistant.last_facts.risk_assessment.dominant_pattern == "forward_collapse"


def test_two_tabs_opening_at_once_leave_a_single_explanation(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, _, analysis_id = await _people(world)
        request = chat_pb2.StartConversationRequest(analysis_id=analysis_id)
        results = await asyncio.gather(
            *(_stream(stub.StartConversation(request, metadata=bearer(athlete))) for _ in range(3))
        )
        return results, await _messages(world)

    results, stored = _run(tmp_path, scenario, _FakeAssistant(delay=0.2))

    assert len(stored) == 1
    assert len({received[-1].assistant_message.id for received, _ in results}) == 1


def test_a_question_comes_back_saved_then_in_parts_and_carries_the_history(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, _, analysis_id = await _people(world)
        await _stream(stub.StartConversation(chat_pb2.StartConversationRequest(analysis_id=analysis_id), metadata=bearer(athlete)))
        request = chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="  ¿Es grave?  ")
        replies, _ = await _stream(stub.SendMessage(request, metadata=bearer(athlete)))
        listed = await stub.ListMessages(chat_pb2.ListMessagesRequest(analysis_id=analysis_id), metadata=bearer(athlete))
        return replies, listed.messages, assistant

    replies, listed, assistant = _run(tmp_path, scenario)

    assert replies[0].user_message.content == "¿Es grave?"
    assert replies[-1].assistant_message.content == "Respuesta a ¿Es grave?"
    assert all(reply.HasField("text_delta") for reply in replies[1:-1])
    assert assistant.questions == [(["Explicación para athlete"], "¿Es grave?")]
    assert [message.role for message in listed] == [
        common_chat_pb2.CHAT_ROLE_ASSISTANT,
        common_chat_pb2.CHAT_ROLE_USER,
        common_chat_pb2.CHAT_ROLE_ASSISTANT,
    ]


def test_if_the_ai_fails_the_question_stays_saved_and_the_stream_ends_unavailable(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, _, analysis_id = await _people(world)
        request = chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="¿Y ahora?")
        replies, error = await _stream(stub.SendMessage(request, metadata=bearer(athlete)))
        return replies, error, await _messages(world)

    replies, error, stored = _run(tmp_path, scenario, _FakeAssistant(fail=True))

    assert replies[0].user_message.content == "¿Y ahora?"
    assert error.code() is grpc.StatusCode.UNAVAILABLE and error_info(error).reason == "ASSISTANT_UNAVAILABLE"
    assert stored == [(ChatRole.USER, "¿Y ahora?")]


def test_past_the_hourly_limit_nothing_is_saved(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, _, analysis_id = await _people(world)
        for question in ("uno", "dos"):
            await _stream(stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content=question), metadata=bearer(athlete)))
        replies, error = await _stream(
            stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="tres"), metadata=bearer(athlete))
        )
        return replies, error, await _messages(world)

    replies, error, stored = _run(tmp_path, scenario, per_hour=2)

    assert replies == []
    assert error.code() is grpc.StatusCode.RESOURCE_EXHAUSTED and error_info(error).reason == "CHAT_RATE_LIMITED"
    assert [content for role, content in stored if role == ChatRole.USER] == ["uno", "dos"]


def test_simultaneous_questions_cannot_pass_the_limit_together(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, _, analysis_id = await _people(world)
        calls = [
            _stream(stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content=f"p{n}"), metadata=bearer(athlete)))
            for n in range(4)
        ]
        results = await asyncio.gather(*calls)
        return results, await _messages(world)

    results, stored = _run(tmp_path, scenario, _FakeAssistant(delay=0.1), per_hour=2)

    limited = [error for _, error in results if error is not None]
    assert len(limited) == 2 and all(error_info(error).reason == "CHAT_RATE_LIMITED" for error in limited)
    assert len([role for role, _ in stored if role == ChatRole.USER]) == 2


def test_the_global_limit_counts_every_conversation(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        coach, athlete, _, analysis_id = await _people(world)
        await _stream(stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="del atleta"), metadata=bearer(athlete)))
        _, error = await _stream(
            stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="del coach"), metadata=bearer(coach))
        )
        return error

    error = _run(tmp_path, scenario, per_minute=1)

    assert error_info(error).reason == "CHAT_RATE_LIMITED"


def test_each_person_has_their_own_thread(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        coach, athlete, _, analysis_id = await _people(world)
        await _stream(stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="solo mío"), metadata=bearer(athlete)))
        listed = await stub.ListMessages(chat_pb2.ListMessagesRequest(analysis_id=analysis_id), metadata=bearer(coach))
        return listed.messages

    assert list(_run(tmp_path, scenario)) == []


@pytest.mark.parametrize(
    ("who", "status", "reason"),
    [
        ("stranger", JumpAnalysisStatus.PROCESSED, "FORBIDDEN"),
        ("athlete", JumpAnalysisStatus.PENDING, "ANALYSIS_NOT_PROCESSED"),
        ("missing", JumpAnalysisStatus.PROCESSED, "NOT_FOUND"),
    ],
)
def test_the_opening_is_refused_without_access_or_before_processing(tmp_path: Path, who: str, status, reason: str) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, stranger, analysis_id = await _people(world, status)
        caller = stranger if who == "stranger" else athlete
        target = analysis_id + 100 if who == "missing" else analysis_id
        _, error = await _stream(stub.StartConversation(chat_pb2.StartConversationRequest(analysis_id=target), metadata=bearer(caller)))
        return error, assistant

    error, assistant = _run(tmp_path, scenario)

    assert error_info(error).reason == reason
    assert assistant.explained == 0


def test_the_admin_does_not_chat_and_long_or_blank_messages_are_invalid(tmp_path: Path) -> None:
    async def scenario(world, stub, assistant):
        _, athlete, _, analysis_id = await _people(world)
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        _, denied = await _stream(stub.StartConversation(chat_pb2.StartConversationRequest(analysis_id=analysis_id), metadata=bearer(admin)))
        _, too_long = await _stream(
            stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="x" * (MAX_CHARS + 1)), metadata=bearer(athlete))
        )
        _, blank = await _stream(stub.SendMessage(chat_pb2.SendMessageRequest(analysis_id=analysis_id, content="   "), metadata=bearer(athlete)))
        return denied, too_long, blank

    denied, too_long, blank = _run(tmp_path, scenario)

    assert denied.code() is grpc.StatusCode.PERMISSION_DENIED
    assert field_violations(too_long) == field_violations(blank) == ["content"]
