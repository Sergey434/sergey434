import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, ErrorEvent

from .config import settings
from .core_api import CoreAPI
from .handlers import router


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    api = CoreAPI(settings.core_url, settings.service_token)
    bot = Bot(settings.bot_token)
    dp = Dispatcher()
    dp["api"] = api  # передаётся в обработчики как аргумент api
    dp.include_router(router)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        logging.exception("Ошибка при обработке апдейта", exc_info=event.exception)
        msg = event.update.message or (event.update.callback_query and event.update.callback_query.message)
        if msg:
            await msg.answer("😔 Что-то пошло не так. Попробуйте ещё раз чуть позже.")
        return True

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать"),
            BotCommand(command="model", description="Выбрать нейросеть"),
            BotCommand(command="new", description="Новый диалог"),
            BotCommand(command="balance", description="Баланс"),
            BotCommand(command="topup", description="Пополнить баланс"),
            BotCommand(command="paysupport", description="Помощь с оплатой"),
        ]
    )
    try:
        await dp.start_polling(bot)
    finally:
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
