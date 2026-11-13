import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)

from .config import settings
from .core_api import CoreAPI, CoreError

router = Router()

BTN_MODEL = "🤖 Модель"
BTN_NEW = "💬 Новый чат"
BTN_BALANCE = "💰 Баланс"
BTN_TOPUP = "➕ Пополнить"

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_MODEL), KeyboardButton(text=BTN_NEW)],
        [KeyboardButton(text=BTN_BALANCE), KeyboardButton(text=BTN_TOPUP)],
    ],
    resize_keyboard=True,
)

TG_LIMIT = 4000  # Telegram допускает 4096 символов в сообщении, оставляем запас
EDIT_INTERVAL = 1.2  # не чаще раза в ~секунду, иначе Telegram начнёт ограничивать


def rub(kopecks: int) -> str:
    return f"{kopecks / 100:.2f} ₽"


# ---------- Основные команды ----------


@router.message(CommandStart())
async def start(message: Message, api: CoreAPI):
    u = message.from_user
    me = await api.ensure_user(u.id, u.username, u.first_name)
    await message.answer(
        f"Привет, {u.first_name or 'друг'}! 👋\n\n"
        "Здесь собраны лучшие нейросети в одном месте. Просто напишите вопрос — отвечу.\n\n"
        f"Текущая модель: {me['selected_model_title']}\n"
        f"Баланс: {rub(me['balance_kopecks'])}\n\n"
        "Команды: /model — выбрать модель, /new — новый диалог, /balance — баланс, /topup — пополнить.",
        reply_markup=MAIN_KB,
    )


@router.message(Command("balance"))
@router.message(F.text == BTN_BALANCE)
async def balance(message: Message, api: CoreAPI):
    me = await api.me(message.from_user.id)
    await message.answer(f"Баланс: {rub(me['balance_kopecks'])}\nМодель: {me['selected_model_title']}")


@router.message(Command("new"))
@router.message(F.text == BTN_NEW)
async def new_chat(message: Message, api: CoreAPI):
    await api.new_conversation(message.from_user.id)
    await message.answer("Начат новый диалог — прошлый контекст забыт. 🧹")


# ---------- Выбор модели ----------


@router.message(Command("model"))
@router.message(F.text == BTN_MODEL)
async def choose_model(message: Message, api: CoreAPI):
    models = await api.models()
    me = await api.me(message.from_user.id)
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if m["id"] == me["selected_model"] else "") + f"{m['title']} — {m['description']}",
                callback_data=f"m:{i}",
            )
        ]
        for i, m in enumerate(models)
    ]
    await message.answer("Выберите модель:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("m:"))
async def model_selected(cb: CallbackQuery, api: CoreAPI):
    models = await api.models()
    idx = int(cb.data[2:])
    if idx >= len(models):
        await cb.answer("Список моделей обновился, откройте /model заново", show_alert=True)
        return
    me = await api.set_model(cb.from_user.id, models[idx]["id"])
    await cb.message.edit_text(f"Готово! Теперь отвечает: {me['selected_model_title']}")
    await cb.answer()


# ---------- Пополнение через Telegram Stars ----------


@router.message(Command("topup"))
@router.message(F.text == BTN_TOPUP)
async def topup_menu(message: Message):
    rows = [
        [
            InlineKeyboardButton(
                text=f"⭐ {stars} → {rub(stars * settings.kopecks_per_star)}", callback_data=f"stars:{stars}"
            )
        ]
        for stars in settings.stars_pack_list
    ]
    await message.answer("Выберите сумму пополнения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("stars:"))
async def send_invoice(cb: CallbackQuery):
    stars = int(cb.data.split(":")[1])
    if stars not in settings.stars_pack_list:
        await cb.answer("Этот вариант больше недоступен", show_alert=True)
        return
    await cb.message.answer_invoice(
        title="Пополнение баланса",
        description=f"Зачисление {rub(stars * settings.kopecks_per_star)} на баланс",
        payload=f"topup:{stars}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="Пополнение", amount=stars)],
        provider_token="",  # для Stars не нужен
    )
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    ok = query.invoice_payload.startswith("topup:")
    await query.answer(ok=ok, error_message=None if ok else "Неизвестный платёж")


@router.message(F.successful_payment)
async def payment_done(message: Message, api: CoreAPI):
    sp = message.successful_payment
    result = await api.topup(
        message.from_user.id,
        amount_kopecks=sp.total_amount * settings.kopecks_per_star,
        provider="telegram_stars",
        external_id=sp.telegram_payment_charge_id,
    )
    await message.answer(f"✅ Оплата получена! Баланс: {rub(result['balance_kopecks'])}")


@router.message(Command("paysupport"))
async def paysupport(message: Message):
    await message.answer(f"Вопросы по оплате и возвратам: {settings.support_contact}")


# ---------- Диалог с моделью ----------


async def _safe_edit(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text or "…")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.message(F.text)
async def ask(message: Message, api: CoreAPI):
    current = await message.answer("⏳ Думаю…")
    buf, offset, last_edit = "", 0, 0.0
    done: dict | None = None
    error: str | None = None

    try:
        async for event in api.chat_stream(message.from_user.id, message.text):
            if event["type"] == "delta":
                buf += event["text"]
                # Длинный ответ — разбиваем на несколько сообщений
                while len(buf) - offset > TG_LIMIT:
                    await _safe_edit(current, buf[offset : offset + TG_LIMIT])
                    offset += TG_LIMIT
                    current = await message.answer("…")
                    last_edit = time.monotonic()
                if time.monotonic() - last_edit > EDIT_INTERVAL:
                    await _safe_edit(current, buf[offset:] + " ▌")
                    last_edit = time.monotonic()
            elif event["type"] == "done":
                done = event
            elif event["type"] == "error":
                error = event["detail"]
    except CoreError as e:
        hints = {
            402: "💸 Недостаточно средств. Пополните баланс: /topup",
            429: "🐢 Слишком много запросов. Подождите минуту.",
        }
        await _safe_edit(current, hints.get(e.status, f"⚠️ {e.detail}"))
        return

    tail = buf[offset:]
    if error:
        tail = (tail + f"\n\n⚠️ {error}").strip()
    footer = ""
    if done:
        footer = f"\n\n— {done['model_title']} · −{rub(done['cost_kopecks'])} · баланс {rub(done['balance_kopecks'])}"
    if len(tail) + len(footer) <= TG_LIMIT:
        await _safe_edit(current, tail + footer)
    else:
        await _safe_edit(current, tail)
        if footer:
            await message.answer(footer.strip())


@router.message()
async def unsupported(message: Message):
    await message.answer("Пока я понимаю только текст. Картинки и файлы — скоро! 🙂")
