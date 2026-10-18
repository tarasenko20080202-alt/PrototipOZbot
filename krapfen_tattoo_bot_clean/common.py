"""Общие настройки и функции для bot.py и server.py."""
import html
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import texts

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("krapfen")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
ADMIN_IDS = {
    int(x)
    for x in re.split(r"[,\s;]+", os.getenv("ADMIN_IDS", ""))
    if x.lstrip("-").isdigit()
}
HANDOFF_HOURS = float(os.getenv("HANDOFF_HOURS") or 12)
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")

esc = html.escape


def require_config(*, need_webapp: bool = True) -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Впишите его в файл .env (см. .env.example).")
    if need_webapp and not WEBAPP_URL.startswith("https://"):
        raise RuntimeError("WEBAPP_URL должен быть публичным адресом, начинающимся с https://")


def client_header(user_id: int, full_name: str, username: str | None) -> str:
    """Шапка для мастера. #id стоит первым — по нему бот понимает, кому отвечать."""
    uname = f"@{username}" if username else "без username"
    return (
        f"#id{user_id} 👤 "
        f'<a href="tg://user?id={user_id}">{esc(full_name)}</a> ({esc(uname)})'
    )


async def notify_admins_text(bot, text: str) -> int:
    """Отправляет текст всем мастерам. Возвращает, скольким дошло."""
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
            sent += 1
        except Exception:
            log.exception("Не удалось написать мастеру (admin_id=%s)", admin_id)
    return sent


def _fmt_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return value or "не выбрана"


async def process_booking(bot, user_id: int, full_name: str, username: str | None, payload: dict) -> bool:
    """Заявка из Mini App: уведомляет мастера и подтверждает клиенту.
    False — если мастеру доставить не удалось (клиент должен узнать об этом)."""
    name = (payload.get("name") or full_name)[:100]
    service = (payload.get("service") or "Татуировка")[:50]
    date = _fmt_date(str(payload.get("date") or ""))
    time_ = str(payload.get("time") or "") or "не выбрано"
    comment = (payload.get("comment") or "—")[:1500]

    admin_text = (
        "📝 <b>Новая заявка</b>\n"
        f"{client_header(user_id, full_name, username)}\n\n"
        f"Имя: {esc(name)}\n"
        f"Услуга: {esc(service)}\n"
        f"Дата: {esc(date)}\n"
        f"Время: {esc(time_)}\n"
        f"Комментарий: {esc(comment)}"
    )
    delivered = await notify_admins_text(bot, admin_text)
    if ADMIN_IDS and not delivered:
        return False

    try:
        await bot.send_message(user_id, texts.booking_client_text(name, service, date, time_, comment))
    except Exception:
        log.exception("Не удалось отправить подтверждение клиенту %s", user_id)
    return True
