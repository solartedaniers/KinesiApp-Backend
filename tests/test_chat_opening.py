"""Primer mensaje automático del chat: la explicación del resultado apenas el análisis está listo."""
from app.chat.llm import LlmUnavailableError
from app.chat.system_prompt import OPENING_REQUEST
from app.models.jump_analysis import JumpAnalysis, JumpAnalysisStatus
from app.models.user import UserRole
from tests.test_chat_endpoints import _processed_analysis, _send
from tests.test_jump_analysis_rbac import _auth_headers


def _opening(client, token: str, analysis_id: int):
    return client.post(f"/api/v1/jump-analyses/{analysis_id}/chat/opening", headers=_auth_headers(token))


def test_opening_explains_the_result_once_with_the_chat_prompt(client, register_and_verify, grant_consent, upload_jump, fake_llm):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "open1@kinesiapp.com")
    fake_llm.reply = "Tu salto muestra un colapso hacia adelante."

    r = _opening(client, token, analysis_id)
    assert r.status_code == 200, r.text
    assert [(m["role"], m["content"]) for m in r.json()] == [("assistant", fake_llm.reply)]
    # Mismo system prompt y mismos datos que el chat; el único turno es el pedido de apertura
    request = fake_llm.requests[0]
    assert '"code": "forward_collapse"' in request.system_instruction
    assert [(turn.role, turn.text) for turn in request.turns] == [("user", OPENING_REQUEST)]

    # Idempotente: volver a abrir la pantalla no llama otra vez al proveedor
    assert _opening(client, token, analysis_id).json() == r.json()
    assert len(fake_llm.requests) == 1


def test_follow_up_questions_keep_the_opening_in_context(client, register_and_verify, grant_consent, upload_jump, fake_llm):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "open2@kinesiapp.com")
    fake_llm.reply = "Explicación inicial."
    _opening(client, token, analysis_id)

    fake_llm.reply = "Respuesta a la pregunta."
    assert _send(client, token, analysis_id, "¿Y el tronco?").status_code == 200
    assert [turn.text for turn in fake_llm.requests[1].turns] == [OPENING_REQUEST, "Explicación inicial.", "¿Y el tronco?"]
    # El pedido de apertura no se guarda ni se muestra: el hilo empieza con la explicación
    thread = client.get(f"/api/v1/jump-analyses/{analysis_id}/chat/messages", headers=_auth_headers(token)).json()
    assert [m["content"] for m in thread] == ["Explicación inicial.", "¿Y el tronco?", "Respuesta a la pregunta."]


def test_each_user_gets_their_own_opening_in_their_tone(client, register_and_verify, grant_consent, upload_jump, set_role, fake_llm):
    token, athlete_id, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "open3@kinesiapp.com")
    coach = register_and_verify("open-coach@kinesiapp.com")
    set_role("open-coach@kinesiapp.com", UserRole.COACH)
    admin = register_and_verify("open-admin@kinesiapp.com")
    set_role("open-admin@kinesiapp.com", UserRole.ADMIN)
    coach_id = client.get("/api/v1/auth/me", headers=_auth_headers(coach)).json()["id"]
    client.patch(f"/api/v1/athletes/{athlete_id}/coach", json={"coach_id": coach_id}, headers=_auth_headers(admin))

    _opening(client, token, analysis_id)
    _opening(client, coach, analysis_id)
    assert '"audience": "athlete"' in fake_llm.requests[0].system_instruction
    assert '"audience": "coach"' in fake_llm.requests[1].system_instruction
    # Mismos permisos que el chat: el admin no conversa y un extraño no ve el análisis
    assert _opening(client, admin, analysis_id).status_code == 403
    stranger = register_and_verify("open-stranger@kinesiapp.com")
    assert _opening(client, stranger, analysis_id).status_code == 403


def test_opening_waits_for_the_analysis_and_degrades_without_storing(
    client, register_and_verify, grant_consent, upload_jump, db_session, fake_llm
):
    token, _, analysis_id = _processed_analysis(client, register_and_verify, grant_consent, upload_jump, "open4@kinesiapp.com")
    analysis = db_session.get(JumpAnalysis, analysis_id)
    analysis.status = JumpAnalysisStatus.PENDING
    db_session.commit()
    assert (_opening(client, token, analysis_id).json()["code"]) == "analysis_not_processed"
    assert fake_llm.requests == []

    analysis.status = JumpAnalysisStatus.PROCESSED
    db_session.commit()
    fake_llm.error = LlmUnavailableError("down")
    assert _opening(client, token, analysis_id).json()["code"] == "assistant_unavailable"
    # Nada guardado: al volver, se reintenta
    fake_llm.error = None
    assert len(_opening(client, token, analysis_id).json()) == 1
