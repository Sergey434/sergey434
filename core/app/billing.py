import math

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .catalog import ModelInfo
from .config import settings
from .models import Transaction, User


def calc_cost_kopecks(model: ModelInfo, usage: dict | None) -> int:
    usage = usage or {}
    if usage.get("cost") is not None:
        usd = float(usage["cost"])  # точная стоимость от OpenRouter
    else:
        usd = (
            int(usage.get("prompt_tokens") or 0) * model.input_usd_per_m
            + int(usage.get("completion_tokens") or 0) * model.output_usd_per_m
        ) / 1_000_000
    if usd <= 0:
        return 0
    return max(1, math.ceil(usd * settings.usd_rub_rate * settings.markup * 100))


async def charge(session: AsyncSession, user_id: int, amount: int, description: str) -> int:
    """Атомарно списывает сумму и возвращает новый баланс.

    Баланс может уйти немного в минус: точная цена известна только после ответа.
    Следующий запрос в этом случае не пройдёт проверку минимального баланса.
    """
    new_balance = await session.scalar(
        update(User)
        .where(User.id == user_id)
        .values(balance=User.balance - amount)
        .returning(User.balance)
    )
    session.add(Transaction(user_id=user_id, amount=-amount, kind="charge", description=description))
    return int(new_balance)


async def topup(
    session: AsyncSession, user_id: int, amount: int, provider: str, external_id: str
) -> tuple[int, bool]:
    """Зачисляет платёж. Возвращает (баланс, зачислено_ли_сейчас).

    Повторный вызов с тем же external_id ничего не зачисляет —
    платёжки иногда присылают уведомление несколько раз.
    """
    existing = await session.scalar(select(Transaction).where(Transaction.external_id == external_id))
    if existing is None:
        session.add(
            Transaction(
                user_id=user_id, amount=amount, kind="topup", provider=provider, external_id=external_id
            )
        )
        balance = await session.scalar(
            update(User).where(User.id == user_id).values(balance=User.balance + amount).returning(User.balance)
        )
        await session.commit()
        return int(balance), True
    balance = await session.scalar(select(User.balance).where(User.id == user_id))
    return int(balance), False
