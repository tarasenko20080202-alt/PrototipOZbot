import asyncio
import json
import re
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReactionTypeEmoji,
    ReplyKeyboardMarkup,
    ReplyParameters,
    WebAppInfo,
)

import texts
from common import (
    ADMIN_IDS,
    BOT_TOKEN,
    DATA_DIR,
    HANDOFF_HOURS,
    WEBAPP_URL,
    client_header,
    esc,
    log,
    notify_admins_text,
    process_booking,
    require_config,
)

router = Router()
router.message.filter(F.chat.type == "private")  # в группах бот молчит

# ───────────────────────── состояние ─────────────────────────
# human_until: после ответа мастера бот не лезет в диалог HANDOFF_HOURS часов.
# Хранится в файле, поэтому переживает перезапуск.
STATE_FILE = DATA_DIR / "state.json"
_human_until: dict[str, float] = {}
_last_ack: dict[int, float] = {}
_last_group: dict[int, str] = {}
ACK_WINDOW = 600  # не чаще раза в 10 минут отвечаем «принял» на сообщения без темы


def load_state() -> None:
    try:
        data = json.loads(STATE_FILE.read_text("utf-8"))
        _human_until.update({k: float(v) for k, v in data.get("human_until", {}).items()})
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("Не удалось прочитать %s — начинаю с чистого состояния", STATE_FILE)


def save_state() -> None:
    now = time.time()
    for key in [k for k, v in _human_until.items() if v < now]:
        del _human_until[key]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"human_until": _human_until}), "utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        log.exception("Не удалось сохранить состояние")


def human_active(user_id: int) -> bool:
    return _human_until.get(str(user_id), 0) > time.time()


def can_ack(user_id: int) -> bool:
    now = time.time()
    if now - _last_ack.get(user_id, 0) < ACK_WINDOW:
        return False
    _last_ack[user_id] = now
    return True


# ───────────────────────── клавиатуры ─────────────────────────
def webapp_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Записаться", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Сообщение...",
    )


def start_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть запись", web_app=WebAppInfo(url=WEBAPP_URL))]
        ]
    )


def works_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Работы", web_app=WebAppInfo(url=f"{WEBAPP_URL}?tab=works"))]
        ]
    )


# ───────────────────────── распознавание вопросов ─────────────────────────
def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


# Порядок важен: берётся первое совпадение.
INTENTS: list[tuple[str, re.Pattern]] = [
    (name, re.compile(pattern))
    for name, pattern in [
        ("thanks", r"^(спасибо|спс|благодарю|ок|окей|ok|хорошо|ладно|понял[аи]?|ясно|договорились)\b[\s!.)]*$"),
        ("greeting", r"^(привет\w*|здравствуй\w*|здрасьте|добр(ый|ое|ая) (день|вечер|утро|ночи)|хай|салют|hello|hi)\b[\s!.,)]*$"),
        ("price", r"\b(цен[аыуе]|ценник\w*|стоимост\w*|прайс\w*|почем\w*|по чем|сколько (это )?(стоит|будет|буд\w+|бер\w+|нужно заплатить))"),
        ("care_problem", r"воспал|гной|гнои|нагно|опух|отек|отеч|покрасн|температур|зудит|чешет|аллерг|жжет"),
        ("booking", r"\bзапис\w*|\bокошк\w*|\bсвободн\w+|ближайш\w+|\bхочу (тату|татуировк\w*|эскиз|набить|сделать)|\bкогда (можно )?(прийти|приехать)"),
        ("care", r"\bуход(а|у|е|ом)?\b|ухажива|зажив\w*|после тату|после сеанса|\bмаз[ьи]\b|\bкрем\w*|пленк\w*|корочк\w*|шелуш\w*|бепантен|панталок"),
        ("reference", r"референс\w*"),
        ("works", r"\bстил\w*|\bпримеры?\b|\bработ(ы|ах|ами)\b|портфолио|\bпокажи\w*"),
        ("thinking", r"не знаю|еще думаю|пока не решил\w*|пока думаю|подумаю|надо подумать"),
    ]
]


def detect_intent(text: str) -> str:
    t = norm(text)
    for name, pattern in INTENTS:
        if pattern.search(t):
            return name
    return "other"


# ───────────────────────── связь с мастером ─────────────────────────
async def forward_to_admins(bot: Bot, message: Message, note: str = "") -> int:
    """Пересылает сообщение клиента мастеру. Возвращает, скольким мастерам дошло."""
    if not ADMIN_IDS:
        return 0
    user = message.from_user
    header = client_header(user.id, user.full_name, user.username)
    if note:
        header += f"\n{note}"
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            if message.photo:
                caption = header
                if message.caption:
                    caption += "\n\n" + esc(message.caption[:800])
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption)
            elif message.text:
                await bot.send_message(admin_id, f"{header}\n\n{esc(message.text[:3500])}")
            else:
                head = await bot.send_message(admin_id, header + "\n(вложение ниже — отвечайте на это сообщение)")
                await message.copy_to(admin_id, reply_parameters=ReplyParameters(message_id=head.message_id))
            sent += 1
        except Exception:
            log.exception("Не удалось переслать сообщение мастеру (admin_id=%s)", admin_id)
    return sent


ID_RE = re.compile(r"#id(\d+)")


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(texts.WELCOME_TEXT)
    await message.answer(texts.START_TEXT, reply_markup=start_inline_keyboard())
    await message.answer(texts.START_HINT, reply_markup=webapp_reply_keyboard())


@router.message(Command("id"))
async def show_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


# Мастер отвечает клиенту свайпом (Reply) по пересланному сообщению
@router.message(F.reply_to_message, F.from_user.id.in_(ADMIN_IDS))
async def admin_reply(message: Message) -> None:
    src = message.reply_to_message
    found = ID_RE.search(src.text or src.caption or "")
    if not found:
        await message.answer(
            "Не понял, кому отвечать. Ответьте (Reply) на сообщение клиента — "
            "то, где сверху есть пометка #id…"
        )
        return
    client_id = int(found.group(1))
    try:
        await message.copy_to(client_id)
    except TelegramForbiddenError:
        await message.answer("Клиент заблокировал бота — сообщение не доставлено.")
        return
    except Exception:
        log.exception("Не удалось отправить ответ клиенту %s", client_id)
        await message.answer("Не удалось отправить ответ клиенту. Попробуйте ещё раз.")
        return
    _human_until[str(client_id)] = time.time() + HANDOFF_HOURS * 3600
    save_state()
    try:
        await message.react([ReactionTypeEmoji(emoji="👍")])
    except Exception:
        pass


# Резервный путь: заявка, пришедшая через sendData (если Mini App запущен с нижней кнопки)
@router.message(F.web_app_data)
async def web_app_data(message: Message, bot: Bot) -> None:
    try:
        payload = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        payload = {}
    if payload.get("action") != "booking_request":
        await message.answer("Ок, данные получил.", reply_markup=webapp_reply_keyboard())
        return
    user = message.from_user
    ok = await process_booking(bot, user.id, user.full_name, user.username, payload)
    if not ok:
        await message.answer("Не получилось передать заявку мастеру. Напишите сюда, что хотите и когда — я передам.")


@router.message(F.photo)
async def photo_message(message: Message, bot: Bot) -> None:
    uid = message.from_user.id
    group = message.media_group_id
    first_in_group = not group or _last_group.get(uid) != group
    if group:
        _last_group[uid] = group
    delivered = await forward_to_admins(bot, message, "🖼 референс")
    if human_active(uid) or not first_in_group or not can_ack(uid):
        return
    await message.answer(
        texts.with_passed(texts.PHOTO_ACK, delivered > 0),
        reply_markup=webapp_reply_keyboard(),
    )


@router.message(F.text)
async def text_message(message: Message, bot: Bot) -> None:
    uid = message.from_user.id
    kb = webapp_reply_keyboard()

    if norm(message.text) == "записаться":
        await message.answer(texts.OPEN_TEXT, reply_markup=kb)
        return

    # Мастер недавно сама отвечает клиенту — бот только передаёт сообщения
    if human_active(uid):
        await forward_to_admins(bot, message)
        return

    intent = detect_intent(message.text)

    if intent == "thanks":
        await message.answer(texts.THANKS, reply_markup=kb)
    elif intent == "greeting":
        await message.answer(texts.GREETING, reply_markup=kb)
    elif intent == "thinking":
        await message.answer(texts.THINKING, reply_markup=kb)
    elif intent == "care":
        await message.answer(texts.CARE, reply_markup=kb)
    elif intent == "reference":
        await message.answer(texts.REFERENCE_INFO, reply_markup=works_inline_keyboard())
    elif intent == "works":
        await message.answer(texts.WORKS, reply_markup=works_inline_keyboard())
    elif intent == "care_problem":
        delivered = await forward_to_admins(bot, message, "⚠️ вопрос по заживлению")
        await message.answer(texts.with_passed(texts.CARE_PROBLEM, delivered > 0), reply_markup=kb)
    elif intent == "price":
        delivered = await forward_to_admins(bot, message, "💰 вопрос о цене")
        await message.answer(texts.with_passed(texts.PRICE, delivered > 0), reply_markup=kb)
    elif intent == "booking":
        delivered = await forward_to_admins(bot, message, "📅 хочет записаться")
        await message.answer(
            texts.with_passed(texts.BOOKING, delivered > 0),
            reply_markup=start_inline_keyboard(),
        )
    else:
        delivered = await forward_to_admins(bot, message)
        if can_ack(uid):
            await message.answer(texts.with_passed(texts.FALLBACK, delivered > 0), reply_markup=kb)


# Голосовые, документы, стикеры и всё остальное
@router.message()
async def other_message(message: Message, bot: Bot) -> None:
    uid = message.from_user.id
    delivered = await forward_to_admins(bot, message, "📎 вложение")
    if human_active(uid) or not can_ack(uid):
        return
    await message.answer(
        texts.with_passed(texts.OTHER_ACK, delivered > 0),
        reply_markup=webapp_reply_keyboard(),
    )


async def main() -> None:
    require_config()
    load_state()
    if not ADMIN_IDS:
        log.warning(
            "ADMIN_IDS не задан: сообщения клиентов НЕ будут пересылаться мастеру. "
            "Узнайте ID командой /id и впишите в .env"
        )
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    # Не сбрасываем накопленные сообщения: если бот перезапускался,
    # клиенты, написавшие в это время, всё равно получат ответ.
    await bot.delete_webhook(drop_pending_updates=False)
    me = await bot.get_me()
    log.info("Бот @%s запущен", me.username)
    await notify_admins_text(bot, "✅ Бот запущен и принимает сообщения.")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
