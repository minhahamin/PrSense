"""LLM factory + deterministic mock (for tests / no-key dev)."""

from __future__ import annotations

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import get_settings


def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        temperature=s.llm_temperature if temperature is None else temperature,
        api_key=s.openai_api_key,
    )


def get_embedding_model() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(model=s.embedding_model, api_key=s.openai_api_key)


def is_mock_mode() -> bool:
    s = get_settings()
    return s.mock_llm or not s.openai_api_key
