"""Каталог моделей, доступных пользователям.

ВАЖНО: идентификаторы и цены ниже — примеры. Перед запуском сверьте их
с актуальным списком на https://openrouter.ai/models и поправьте.

Цены указываются как у провайдера: в долларах за 1 млн токенов.
Если OpenRouter вернул точную стоимость запроса (usage.cost), берётся она,
а эти цены используются только как запасной вариант.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelInfo:
    id: str  # идентификатор в OpenRouter
    title: str  # название для пользователя
    input_usd_per_m: float
    output_usd_per_m: float
    description: str = ""


MODELS: list[ModelInfo] = [
    ModelInfo("openai/gpt-4o-mini", "GPT-4o mini", 0.15, 0.60, "Быстрая и дешёвая"),
    ModelInfo("anthropic/claude-sonnet-4", "Claude Sonnet", 3.0, 15.0, "Тексты и код"),
    ModelInfo("google/gemini-2.5-flash", "Gemini Flash", 0.30, 2.50, "Быстрая, большой контекст"),
    ModelInfo("deepseek/deepseek-chat", "DeepSeek", 0.30, 1.20, "Недорогая универсальная"),
]

_BY_ID = {m.id: m for m in MODELS}


def get_model(model_id: str) -> ModelInfo | None:
    return _BY_ID.get(model_id)


def public_list() -> list[dict]:
    return [asdict(m) for m in MODELS]
