"""Два способа войти в ядро:

1. Бот (доверенный сервис): заголовки X-Service-Token + X-Telegram-Id.
2. Сайт: JWT в заголовке Authorization: Bearer, выдаётся после входа через Telegram Login.
"""

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from .models import User
from .users import get_or_create_by_telegram


def verify_service_token(token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token, settings.service_token)


async def require_service(x_service_token: str | None = Header(None)) -> None:
    if not verify_service_token(x_service_token):
        raise HTTPException(401, "Неверный сервисный токен")


def create_jwt(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_telegram_login(data: dict, bot_token: str, max_age: int = 86400) -> bool:
    """Проверка подписи виджета Telegram Login:
    https://core.telegram.org/widgets/login#checking-authorization
    """
    data = dict(data)
    received = data.pop("hash", None)
    if not received or not bot_token or "auth_date" not in data:
        return False
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()) if v is not None)
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(received)):
        return False
    return time.time() - int(data["auth_date"]) < max_age


async def current_user(
    session: AsyncSession = Depends(get_session),
    x_service_token: str | None = Header(None),
    x_telegram_id: int | None = Header(None),
    authorization: str | None = Header(None),
) -> User:
    user: User | None = None
    if x_service_token is not None:
        if not verify_service_token(x_service_token):
            raise HTTPException(401, "Неверный сервисный токен")
        if x_telegram_id is None:
            raise HTTPException(400, "Нужен заголовок X-Telegram-Id")
        user = await get_or_create_by_telegram(session, x_telegram_id)
    elif authorization and authorization.lower().startswith("bearer "):
        try:
            payload = jwt.decode(authorization[7:], settings.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(401, "Сессия недействительна, войдите заново")
        user = await session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(401, "Требуется авторизация")
    if user.is_blocked:
        raise HTTPException(403, "Аккаунт заблокирован")
    return user
