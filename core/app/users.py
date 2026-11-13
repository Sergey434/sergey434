from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Transaction, User


async def get_or_create_by_telegram(
    session: AsyncSession, telegram_id: int, username: str | None = None, first_name: str | None = None
) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is not None:
        changed = False
        if username is not None and user.username != username:
            user.username, changed = username, True
        if first_name is not None and user.first_name != first_name:
            user.first_name, changed = first_name, True
        if changed:
            await session.commit()
        return user

    bonus = settings.welcome_bonus_kopecks
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        balance=bonus,
        selected_model=settings.default_model,
    )
    session.add(user)
    try:
        await session.flush()
        if bonus:
            session.add(Transaction(user_id=user.id, amount=bonus, kind="bonus", description="Приветственный бонус"))
        await session.commit()
    except IntegrityError:
        # Два одновременных первых запроса от одного пользователя
        await session.rollback()
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    return user
