import hashlib
import hmac
import json
import os
import tempfile
import time

# Настройки задаются до импорта приложения: SQLite вместо Postgres, без Redis, тестовый режим модели
_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_db}",
    REDIS_URL="",
    OPENROUTER_API_KEY="",
    SERVICE_TOKEN="test-service",
    JWT_SECRET="test-jwt-secret-that-is-long-enough-32b",
    BOT_TOKEN="123:ABC",
    WELCOME_BONUS_KOPECKS="1000",
    RATE_LIMIT_PER_MINUTE="5",
)

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.auth import verify_telegram_login  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

SVC = {"X-Service-Token": "test-service"}


def bot(tg_id: int) -> dict:
    return {**SVC, "X-Telegram-Id": str(tg_id)}


@pytest.fixture(scope="session")
async def client():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def chat(client, headers, text, **extra) -> list[dict]:
    async with client.stream("POST", "/v1/chat", headers=headers, json={"message": text, **extra}) as r:
        assert r.status_code == 200, await r.aread()
        return [json.loads(line[6:]) async for line in r.aiter_lines() if line.startswith("data: ")]


async def test_new_user_gets_bonus(client):
    r = await client.post("/internal/users/ensure", headers=SVC, json={"telegram_id": 1, "username": "a"})
    assert r.status_code == 200
    assert r.json()["balance_kopecks"] == 1000


async def test_rejects_bad_service_token(client):
    r = await client.get("/v1/me", headers={"X-Service-Token": "wrong", "X-Telegram-Id": "1"})
    assert r.status_code == 401
    r = await client.post("/internal/topup", json={"telegram_id": 1, "amount_kopecks": 1, "provider": "x", "external_id": "x"})
    assert r.status_code == 401


async def test_chat_streams_and_charges(client):
    events = await chat(client, bot(2), "Привет")
    text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "Привет" in text
    done = events[-1]
    assert done["type"] == "done" and done["cost_kopecks"] > 0
    assert done["balance_kopecks"] == 1000 - done["cost_kopecks"]

    # История сохраняется в диалоге
    convs = (await client.get("/v1/conversations", headers=bot(2))).json()
    msgs = (await client.get(f"/v1/conversations/{convs[0]['id']}/messages", headers=bot(2))).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]

    # Чужой диалог недоступен
    r = await client.get(f"/v1/conversations/{convs[0]['id']}/messages", headers=bot(3))
    assert r.status_code == 404


async def test_select_model(client):
    r = await client.put("/v1/me/model", headers=bot(4), json={"model": "deepseek/deepseek-chat"})
    assert r.json()["selected_model"] == "deepseek/deepseek-chat"
    assert (await chat(client, bot(4), "hi"))[-1]["model"] == "deepseek/deepseek-chat"
    r = await client.put("/v1/me/model", headers=bot(4), json={"model": "nope"})
    assert r.status_code == 400


async def test_topup_is_idempotent(client):
    body = {"telegram_id": 5, "amount_kopecks": 5000, "provider": "telegram_stars", "external_id": "pay-1"}
    first = (await client.post("/internal/topup", headers=SVC, json=body)).json()
    second = (await client.post("/internal/topup", headers=SVC, json=body)).json()
    assert first == {"balance_kopecks": 6000, "credited": True}
    assert second == {"balance_kopecks": 6000, "credited": False}


async def test_no_balance_blocks_chat(client):
    from app.db import SessionLocal
    from app.models import User
    from sqlalchemy import update

    await client.get("/v1/me", headers=bot(6))
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.telegram_id == 6).values(balance=0))
        await s.commit()
    r = await client.post("/v1/chat", headers=bot(6), json={"message": "hi"})
    assert r.status_code == 402


async def test_rate_limit(client):
    codes = []
    for _ in range(7):
        r = await client.post("/v1/chat", headers=bot(7), json={"message": "x"})
        codes.append(r.status_code)
    assert codes.count(429) >= 1


def _signed(data: dict, token: str) -> dict:
    s = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    h = hmac.new(hashlib.sha256(token.encode()).digest(), s.encode(), hashlib.sha256).hexdigest()
    return {**data, "hash": h}


async def test_web_login_shares_account_with_bot(client):
    await client.post("/internal/topup", headers=SVC, json={"telegram_id": 8, "amount_kopecks": 100, "provider": "x", "external_id": "pay-8"})
    data = _signed({"id": 8, "first_name": "Web", "auth_date": int(time.time())}, "123:ABC")
    r = await client.post("/v1/auth/telegram", json=data)
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = (await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})).json()
    assert me["telegram_id"] == 8 and me["balance_kopecks"] == 1100


def test_telegram_login_rejects_forgery():
    data = _signed({"id": 9, "auth_date": int(time.time())}, "123:ABC")
    assert verify_telegram_login(data, "123:ABC")
    assert not verify_telegram_login({**data, "id": 10}, "123:ABC")
    old = _signed({"id": 9, "auth_date": int(time.time()) - 2 * 86400}, "123:ABC")
    assert not verify_telegram_login(old, "123:ABC")
