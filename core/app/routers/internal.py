"""Служебные методы — только для бота и других доверенных сервисов."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import billing
from ..auth import require_service
from ..db import get_session
from ..users import get_or_create_by_telegram
from .account import user_out

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_service)])


class EnsureUser(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None


@router.post("/users/ensure")
async def ensure_user(body: EnsureUser, session: AsyncSession = Depends(get_session)):
    user = await get_or_create_by_telegram(session, body.telegram_id, body.username, body.first_name)
    return user_out(user)


class TopUp(BaseModel):
    telegram_id: int
    amount_kopecks: int = Field(gt=0)
    provider: str
    external_id: str  # id платежа у провайдера — защита от двойного зачисления


@router.post("/topup")
async def topup(body: TopUp, session: AsyncSession = Depends(get_session)):
    user = await get_or_create_by_telegram(session, body.telegram_id)
    balance, credited = await billing.topup(session, user.id, body.amount_kopecks, body.provider, body.external_id)
    return {"balance_kopecks": balance, "credited": credited}
