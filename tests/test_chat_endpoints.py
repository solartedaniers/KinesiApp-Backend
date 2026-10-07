"""Endpoints de chat con un LlmClient falso (conftest.fake_llm): nunca se llama a Gemini."""
from kinesiapp_ai.chat.llm import LlmUnavailableError

from app.core.config import settings
from app.models.chat import ChatConversation
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus
from app.models.user import UserRole
from app.repositories.chat_repository import ChatConversationRepository
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile, _user_id


def _url(analysis_id: int) -> str:
    return f"/api/v1/jump-analyses/{analysis_id}/chat/messages"


def _processed_analysis(client, register_and_verify, grant_consent, upload_jump, email: str) -> tuple[str, int, int]:
    token = register_and_verify(email)
    athlete_id = _create_athlete_profile(client, token)
    grant_consent(token)
    r = upload_jump(token, athlete_id)
    assert r.status_code == 202, r.text
    return token, athlete_id, r.json()["id"]


def _send(client, token: str, analysis_id: int, content: str = "¿Qué debería corregir?"):
    return client.post(_url(analysis_id), json={"content": content}, headers=_auth_headers(token))


def test_athlete_chats_and_reads_back_the_thread(client, register_and_verify, grant_consent, upload_jump, fake_llm):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "chat1@kinesiapp.com")

    r = _send(client, token, analysis_id)
    assert r.status_code == 200, r.text
    assert (r.json()["role"], r.json()["content"]) == ("assistant", fake_llm.reply)
    # El prompt sale del análisis (aquí, el del analizador de prueba: modo reducido)
    assert '"code": "forward_collapse"' in fake_llm.requests[0].system_instruction

    r = client.get(_url(analysis_id), headers=_auth_headers(token))
    assert [(m["role"], m["content"]) for m in r.json()] == [
        ("user", "¿Qué debería corregir?"),
        ("assistant", fake_llm.reply),
    ]
    # El segundo mensaje viaja con el historial del hilo
    _send(client, token, analysis_id, "¿Y el tronco?")
    assert [turn.text for turn in fake_llm.requests[1].turns] == ["¿Qué debería corregir?", fake_llm.reply, "¿Y el tronco?"]


def test_coach_and_athlete_have_separate_threads_and_strangers_are_rejected(
    client, register_and_verify, grant_consent, upload_jump, set_role, fake_llm
):
    athlete_token, athlete_id, analysis_id = _processed_analysis(
        client, register_and_verify, grant_consent, upload_jump, "chat2@kinesiapp.com"
    )
    coach_token = register_and_verify("chatcoach@kinesiapp.com")
    set_role("chatcoach@kinesiapp.com", UserRole.COACH)
    admin_token = register_and_verify("chatadmin@kinesiapp.com")
    set_role("chatadmin@kinesiapp.com", UserRole.ADMIN)

    # Coach todavía no asignado y otro deportista: sin acceso
    assert _send(client, coach_token, analysis_id).status_code == 403
    stranger_token = register_and_verify("chatstranger@kinesiapp.com")
    assert client.get(_url(analysis_id), headers=_auth_headers(stranger_token)).status_code == 403

    client.patch(
        f"/api/v1/athletes/{athlete_id}/coach",
        json={"coach_id": _user_id(client, coach_token)},
        headers=_auth_headers(admin_token),
    )
    _send(client, athlete_token, analysis_id, "pregunta del deportista")
    assert _send(client, coach_token, analysis_id, "pregunta del coach").status_code == 200
    # El admin administra, no conversa sobre análisis (Fase 4: el chat es de deportista y coach)
    assert _send(client, admin_token, analysis_id, "pregunta del admin").status_code == 403

    coach_thread = client.get(_url(analysis_id), headers=_auth_headers(coach_token)).json()
    athlete_thread = client.get(_url(analysis_id), headers=_auth_headers(athlete_token)).json()
    assert [m["content"] for m in coach_thread if m["role"] == "user"] == ["pregunta del coach"]
    assert [m["content"] for m in athlete_thread if m["role"] == "user"] == ["pregunta del deportista"]
    # El tono depende del rol de quien pregunta
    assert '"audience": "coach"' in fake_llm.requests[1].system_instruction


def test_unprocessed_analysis_is_a_conflict(client, register_and_verify, grant_consent, upload_jump, db_session, fake_llm):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "chat3@kinesiapp.com")
    db_session.get(JumpAnalysis, analysis_id).status = JumpAnalysisStatus.PENDING
    db_session.commit()

    r = _send(client, token, analysis_id)
    assert (r.status_code, r.json()["code"]) == (409, "analysis_not_processed")
    assert fake_llm.requests == []


def test_rate_limit_answers_429_without_calling_the_assistant(
    client, register_and_verify, grant_consent, upload_jump, monkeypatch, fake_llm
):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "chat4@kinesiapp.com")
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT_PER_USER_PER_HOUR", 1)

    assert _send(client, token, analysis_id).status_code == 200
    r = _send(client, token, analysis_id)
    assert (r.status_code, r.json()["code"]) == (429, "chat_rate_limited")
    assert len(fake_llm.requests) == 1


def test_assistant_failure_degrades_to_503_and_keeps_only_the_user_message(
    client, register_and_verify, grant_consent, upload_jump, fake_llm
):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "chat5@kinesiapp.com")
    fake_llm.error = LlmUnavailableError("quota exhausted")

    r = _send(client, token, analysis_id)
    assert (r.status_code, r.json()["code"]) == (503, "assistant_unavailable")
    thread = client.get(_url(analysis_id), headers=_auth_headers(token)).json()
    assert [m["role"] for m in thread] == ["user"]

    # Al volver el servicio, el mensaje sin respuesta no se reenvía como historial
    fake_llm.error = None
    assert _send(client, token, analysis_id, "otra vez").status_code == 200
    assert [turn.text for turn in fake_llm.requests[-1].turns] == ["otra vez"]


def test_message_length_is_validated(client, register_and_verify, grant_consent, upload_jump, fake_llm):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "chat6@kinesiapp.com")
    assert _send(client, token, analysis_id, "").status_code == 422
    assert _send(client, token, analysis_id, "x" * (settings.CHAT_MESSAGE_MAX_CHARS + 1)).status_code == 422


def test_unknown_analysis_is_404(client, register_and_verify, fake_llm):
    token = register_and_verify("chat7@kinesiapp.com")
    assert client.get(_url(999), headers=_auth_headers(token)).status_code == 404


def test_concurrent_first_messages_reuse_the_thread_created_by_the_other_request(
    client, register_and_verify, grant_consent, upload_jump, db_session, monkeypatch, fake_llm
):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "chat8@kinesiapp.com")
    # El otro request ganó la carrera: su hilo ya está en la base...
    winner = ChatConversation(jump_analysis_id=analysis_id, user_id=_user_id(client, token))
    db_session.add(winner)
    db_session.commit()
    # ...pero este request lo buscó antes de que existiera
    real_find = ChatConversationRepository.find
    lookups = []

    def find_after_race(self, jump_analysis_id, user_id):
        lookups.append(user_id)
        return None if len(lookups) == 1 else real_find(self, jump_analysis_id, user_id)

    monkeypatch.setattr(ChatConversationRepository, "find", find_after_race)

    r = _send(client, token, analysis_id)
    assert r.status_code == 200, r.text
    assert len(lookups) == 2
    db_session.expire_all()
    assert db_session.query(ChatConversation).count() == 1
    assert [m.role.value for m in db_session.get(ChatConversation, winner.id).messages] == ["user", "assistant"]
