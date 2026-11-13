from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import llm
from .config import settings
from .db import init_db
from .ratelimit import limiter
from .routers import account, chat, internal


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await llm.close()
    await limiter.close()


app = FastAPI(title=f"{settings.app_name} — Core API", lifespan=lifespan)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(account.router)
app.include_router(chat.router)
app.include_router(internal.router)


@app.get("/health")
async def health():
    return {"status": "ok", "mock_mode": not settings.openrouter_api_key}
