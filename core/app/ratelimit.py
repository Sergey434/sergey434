import time

from redis.asyncio import Redis

from .config import settings


class RateLimiter:
    """Счётчик запросов в окне фиксированной длины (по умолчанию минута)."""

    def __init__(self, redis_url: str):
        self.redis = Redis.from_url(redis_url) if redis_url else None
        self._mem: dict[str, int] = {}

    async def hit(self, key: str, limit: int, window: int = 60) -> bool:
        k = f"rl:{key}:{int(time.time() // window)}"
        if self.redis is not None:
            n = await self.redis.incr(k)
            if n == 1:
                await self.redis.expire(k, window)
        else:
            if len(self._mem) > 10_000:
                self._mem.clear()
            n = self._mem.get(k, 0) + 1
            self._mem[k] = n
        return n <= limit

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()


limiter = RateLimiter(settings.redis_url)
