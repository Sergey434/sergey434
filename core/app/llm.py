"""Клиент к OpenRouter (OpenAI-совместимый API) с потоковой выдачей."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from .config import settings


@dataclass
class Chunk:
    text: str | None = None
    usage: dict | None = None


class LLMError(Exception):
    pass


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=300.0))
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def stream_chat(model: str, messages: list[dict]) -> AsyncIterator[Chunk]:
    if not settings.openrouter_api_key:
        async for chunk in _mock_stream(messages):
            yield chunk
        return

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "X-Title": settings.app_name,
    }
    if settings.public_url:
        headers["HTTP-Referer"] = settings.public_url

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "usage": {"include": True},  # вернуть токены и точную стоимость в последнем чанке
    }

    url = f"{settings.openrouter_base_url}/chat/completions"
    async with _get_client().stream("POST", url, headers=headers, json=payload) as resp:
        if resp.status_code != 200:
            body = (await resp.aread()).decode(errors="replace")[:500]
            raise LLMError(f"Провайдер вернул {resp.status_code}: {body}")

        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue  # пустые строки и служебные комментарии SSE
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if "error" in event:
                raise LLMError(str(event["error"].get("message", event["error"])))
            for choice in event.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield Chunk(text=text)
            if event.get("usage"):
                yield Chunk(usage=event["usage"])


async def _mock_stream(messages: list[dict]) -> AsyncIterator[Chunk]:
    """Тестовый режим без ключа: позволяет проверить бота и биллинг бесплатно."""
    last = messages[-1]["content"] if messages else ""
    answer = f"[Тестовый режим: не задан OPENROUTER_API_KEY] Вы написали: {last}"
    for word in answer.split(" "):
        await asyncio.sleep(0.02)
        yield Chunk(text=word + " ")
    prompt_chars = sum(len(m["content"]) for m in messages)
    yield Chunk(usage={"prompt_tokens": prompt_chars // 4 + 1, "completion_tokens": len(answer) // 4 + 1})
