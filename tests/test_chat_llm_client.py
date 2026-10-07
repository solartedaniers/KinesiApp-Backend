"""build_llm_client: qué cliente de LLM se arma según Settings."""
import pytest
from pydantic import SecretStr

from kinesiapp_ai.chat.gemini_client import GeminiLlmClient
from kinesiapp_ai.chat.llm import LlmRequest, LlmTurn, LlmUnavailableError, UnconfiguredLlmClient

from app.core.config import settings
from app.services.chat_factory import build_llm_client

REQUEST = LlmRequest(system_instruction="instrucciones", turns=[LlmTurn(role="user", text="hola")])


def test_without_api_key_the_chat_degrades_instead_of_failing_at_startup(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    client = build_llm_client(settings)
    assert isinstance(client, UnconfiguredLlmClient)
    with pytest.raises(LlmUnavailableError):
        client.generate_reply(REQUEST)

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    assert isinstance(build_llm_client(settings), GeminiLlmClient)
