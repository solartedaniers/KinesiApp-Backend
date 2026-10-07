from functools import lru_cache

from kinesiapp_ai.chat.gemini_client import GeminiLlmClient
from kinesiapp_ai.chat.llm import LlmClient, UnconfiguredLlmClient
from kinesiapp_ai.chat.pattern_catalog import RiskPatternCatalog
from kinesiapp_ai.chat.prompt_builder import JumpAnalysisPromptBuilder

from app.core.config import Settings, settings


def build_llm_client(config: Settings) -> LlmClient:
    if config.GEMINI_API_KEY is None or not config.GEMINI_API_KEY.get_secret_value():
        return UnconfiguredLlmClient()
    return GeminiLlmClient(
        api_key=config.GEMINI_API_KEY.get_secret_value(),
        model_name=config.GEMINI_MODEL,
        timeout_seconds=config.GEMINI_TIMEOUT_SECONDS,
        max_output_tokens=config.GEMINI_MAX_OUTPUT_TOKENS,
    )


def build_prompt_builder(config: Settings) -> JumpAnalysisPromptBuilder:
    return JumpAnalysisPromptBuilder(
        catalog=RiskPatternCatalog([config.RISK_JUMP_PATTERNS, config.RISK_SQUAT_PATTERNS]),
        risk_level_moderate=config.RISK_LEVEL_MODERATE,
        risk_level_high=config.RISK_LEVEL_HIGH,
        max_repetitions=config.CHAT_PROMPT_MAX_REPETITIONS,
        max_history_messages=config.CHAT_HISTORY_MAX_MESSAGES,
    )


@lru_cache
def get_llm_client() -> LlmClient:
    # Un cliente HTTP por proceso, reutilizado entre requests
    return build_llm_client(settings)


@lru_cache
def get_prompt_builder() -> JumpAnalysisPromptBuilder:
    return build_prompt_builder(settings)
