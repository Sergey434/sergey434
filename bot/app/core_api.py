"""HTTP-клиент к ядру. Бот не хранит данных сам — всё в ядре, общем с сайтом."""

import json
from collections.abc import AsyncIterator

import httpx


class CoreError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class CoreAPI:
    def __init__(self, base_url: str, service_token: str):
        self._token = service_token
        self._client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(15.0, read=300.0))

    def _headers(self, tg_id: int | None = None) -> dict:
        h = {"X-Service-Token": self._token}
        if tg_id is not None:
            h["X-Telegram-Id"] = str(tg_id)
        return h

    @staticmethod
    def _check(r: httpx.Response) -> dict | list:
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise CoreError(r.status_code, str(detail))
        return r.json()

    async def ensure_user(self, tg_id: int, username: str | None, first_name: str | None) -> dict:
        r = await self._client.post(
            "/internal/users/ensure",
            headers=self._headers(),
            json={"telegram_id": tg_id, "username": username, "first_name": first_name},
        )
        return self._check(r)

    async def me(self, tg_id: int) -> dict:
        return self._check(await self._client.get("/v1/me", headers=self._headers(tg_id)))

    async def models(self) -> list[dict]:
        return self._check(await self._client.get("/v1/models"))

    async def set_model(self, tg_id: int, model: str) -> dict:
        return self._check(await self._client.put("/v1/me/model", headers=self._headers(tg_id), json={"model": model}))

    async def new_conversation(self, tg_id: int) -> dict:
        return self._check(await self._client.post("/v1/conversations", headers=self._headers(tg_id)))

    async def topup(self, tg_id: int, amount_kopecks: int, provider: str, external_id: str) -> dict:
        r = await self._client.post(
            "/internal/topup",
            headers=self._headers(),
            json={
                "telegram_id": tg_id,
                "amount_kopecks": amount_kopecks,
                "provider": provider,
                "external_id": external_id,
            },
        )
        return self._check(r)

    async def chat_stream(self, tg_id: int, text: str) -> AsyncIterator[dict]:
        async with self._client.stream(
            "POST", "/v1/chat", headers=self._headers(tg_id), json={"message": text}
        ) as r:
            if r.status_code >= 400:
                await r.aread()
                self._check(r)
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])

    async def close(self) -> None:
        await self._client.aclose()
