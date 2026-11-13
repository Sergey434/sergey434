from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_jwt, current_user, verify_telegram_login
from ..catalog import get_model, public_list
from ..config import settings
from ..db import get_session
from ..models import Conversation, Message, User
from ..users import get_or_create_by_telegram

router = APIRouter(prefix="/v1", tags=["account"])


def user_out(user: User) -> dict:
    model = get_model(user.selected_model)
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "balance_kopecks": user.balance,
        "selected_model": user.selected_model,
        "selected_model_title": model.title if model else user.selected_model,
    }


@router.get("/models")
async def models():
    return public_list()


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return user_out(user)


class SetModel(BaseModel):
    model: str


@router.put("/me/model")
async def set_model(body: SetModel, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if get_model(body.model) is None:
        raise HTTPException(400, "Неизвестная модель")
    user = await session.merge(user)
    user.selected_model = body.model
    await session.commit()
    return user_out(user)


@router.post("/conversations")
async def new_conversation(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    conv = Conversation(user_id=user.id)
    session.add(conv)
    await session.commit()
    return {"id": conv.id}


@router.get("/conversations")
async def list_conversations(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.id.desc()).limit(100)
    )
    return [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in rows]


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Диалог не найден")
    rows = await session.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id))
    return [
        {"id": m.id, "role": m.role, "content": m.content, "model": m.model, "cost_kopecks": m.cost} for m in rows
    ]


@router.post("/auth/telegram")
async def auth_telegram(data: dict, session: AsyncSession = Depends(get_session)):
    """Вход на сайте через виджет Telegram Login. Тот же аккаунт и баланс, что в боте."""
    if not verify_telegram_login(data, settings.bot_token):
        raise HTTPException(401, "Не удалось подтвердить вход через Telegram")
    user = await get_or_create_by_telegram(session, int(data["id"]), data.get("username"), data.get("first_name"))
    return {"access_token": create_jwt(user.id), "token_type": "bearer", "user": user_out(user)}
