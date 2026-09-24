"""LLM factory + deterministic mock (for tests / no-key dev)."""

from __future__ import annotations

import json
from typing import TypeVar

import structlog
from pydantic import BaseModel

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import get_settings

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)


def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    s = get_settings()
    kwargs: dict = {
        "model": s.llm_model,
        "temperature": s.llm_temperature if temperature is None else temperature,
        "api_key": s.openai_api_key,
        # hang 방지: 무료 티어 429/무응답 시 빠르게 실패하고 재시도
        "request_timeout": s.llm_timeout,
        "max_retries": s.llm_max_retries,
    }
    if s.llm_base_url:
        kwargs["base_url"] = s.llm_base_url
    if s.llm_max_tokens > 0:
        # OpenRouter 무료 크레딧처럼 예산이 빡빡할 때 예약 토큰 상한을 제한
        kwargs["max_tokens"] = s.llm_max_tokens
    return ChatOpenAI(**kwargs)


def get_embedding_model() -> OpenAIEmbeddings:
    s = get_settings()
    kwargs: dict = {"model": s.embedding_model, "api_key": s.openai_api_key}
    if s.llm_base_url:
        # OpenAIEmbeddings uses openai_api_base in this langchain-openai version
        kwargs["openai_api_base"] = s.llm_base_url
    return OpenAIEmbeddings(**kwargs)


def is_mock_mode() -> bool:
    s = get_settings()
    return s.mock_llm or not s.openai_api_key


def invoke_structured(schema: type[T], messages: list) -> T:
    """Structured output that also works with free/tool-call-less models.

    1) Try native tool calling (OpenAI, GPT-mini, Qwen, GLM with tools…).
    2) Fall back to "JSON only" prompt + salvage parsing (Gemma-style models).
    Raises the last error if both fail.
    """
    llm = get_chat_model()
    try:
        return llm.with_structured_output(schema).invoke(messages)
    except Exception as e:  # noqa: BLE001
        log.warning("tool-calling failed, trying JSON mode",
                    schema=schema.__name__, error=str(e)[:200])

    schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)[:4000]
    json_messages = list(messages) + [
        ("user",
         "Respond with ONLY a valid JSON object matching this JSON Schema. "
         "No markdown fences, no prose, no explanation:\n" + schema_hint)
    ]
    raw = llm.invoke(json_messages).content
    if not isinstance(raw, str):
        raw = str(raw)
    text = raw.strip()
    # strip ```json fences if present
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    # salvage: first { … last }
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in model output: {text[:300]}")
    return schema.model_validate(json.loads(text[start : end + 1]))
