import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import billing, llm
from ..auth import current_user
from ..catalog import get_model
from ..config import settings
from ..db import SessionLocal, get_session
from ..models import Conversation, Message, User
from ..ratelimit import limiter

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None  # по умолчанию — модель, выбранная пользователем
    conversation_id: int | None = None  # по умолчанию — последний диалог


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _resolve_conversation(session: AsyncSession, user: User, conversation_id: int | None) -> Conversation:
    if conversation_id is not None:
        conv = await session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(404, "Диалог не найден")
        return conv
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    if conv is None:
        conv = Conversation(user_id=user.id)
        session.add(conv)
        await session.flush()
    return conv


@router.post("/chat")
async def chat(
    req: ChatRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить сообщение модели. Ответ приходит потоком (Server-Sent Events):
    {"type":"delta","text":...} ... {"type":"done","cost_kopecks":...,"balance_kopecks":...}
    или {"type":"error","detail":...}
    """
    model = get_model(req.model or user.selected_model)
    if model is None:
        raise HTTPException(400, "Неизвестная модель")
    if len(req.message) > settings.max_message_chars:
        raise HTTPException(413, f"Сообщение длиннее {settings.max_message_chars} символов")
    if not await limiter.hit(f"user:{user.id}", settings.rate_limit_per_minute):
        raise HTTPException(429, "Слишком много запросов, подождите минуту")
    if user.balance < settings.min_balance_kopecks:
        raise HTTPException(402, "Недостаточно средств на балансе")

    conv = await _resolve_conversation(session, user, req.conversation_id)
    history = list(
        reversed(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.id.desc())
                    .limit(settings.history_messages)
                )
            ).all()
        )
    )
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": req.message})

    if conv.title is None:
        conv.title = req.message[:120]
    session.add(Message(conversation_id=conv.id, role="user", content=req.message))
    await session.commit()

    user_id, conv_id = user.id, conv.id

    async def generate():
        parts: list[str] = []
        usage: dict | None = None
        try:
            async for chunk in llm.stream_chat(model.id, messages):
                if chunk.text:
                    parts.append(chunk.text)
                    yield _sse({"type": "delta", "text": chunk.text})
                if chunk.usage:
                    usage = chunk.usage
        except Exception as e:  # noqa: BLE001 — любую ошибку провайдера показываем пользователю
            detail = str(e) if isinstance(e, llm.LLMError) else "Ошибка соединения с моделью"
            yield _sse({"type": "error", "detail": detail})
            if not parts:
                return  # ничего не сгенерировано — ничего не списываем

        text = "".join(parts)
        if usage is None:
            # Провайдер не прислал статистику: оцениваем грубо (≈4 символа на токен)
            usage = {
                "prompt_tokens": sum(len(m["content"]) for m in messages) // 4,
                "completion_tokens": len(text) // 4,
            }
        cost = billing.calc_cost_kopecks(model, usage)

        # Отдельная сессия: сессия запроса к этому моменту может быть уже закрыта
        async with SessionLocal() as s:
            s.add(
                Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=text,
                    model=model.id,
                    tokens_in=int(usage.get("prompt_tokens") or 0),
                    tokens_out=int(usage.get("completion_tokens") or 0),
                    cost=cost,
                )
            )
            balance = await billing.charge(s, user_id, cost, f"Запрос к {model.id}")
            await s.commit()

        yield _sse(
            {
                "type": "done",
                "model": model.id,
                "model_title": model.title,
                "conversation_id": conv_id,
                "cost_kopecks": cost,
                "balance_kopecks": balance,
            }
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
