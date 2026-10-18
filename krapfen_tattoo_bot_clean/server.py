import time
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.web_app import safe_parse_webapp_init_data
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from common import BASE_DIR, BOT_TOKEN, log, process_booking, require_config

require_config(need_webapp=False)

WEBAPP_DIR = BASE_DIR / "webapp"
bot: Bot | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global bot
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    yield
    await bot.session.close()


app = FastAPI(
    title="krapfen tattoo mini app",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=WEBAPP_DIR), name="static")


class BookingIn(BaseModel):
    initData: str = Field(max_length=4000)
    name: str = Field(min_length=1, max_length=100)
    comment: str = Field(min_length=1, max_length=2000)
    service: str = Field("Татуировка", max_length=50)
    date: str = Field("", max_length=20)
    time: str = Field("", max_length=10)


@app.get("/")
async def index():
    return FileResponse(WEBAPP_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/booking")
async def booking(data: BookingIn):
    # Проверяем, что запрос реально пришёл из Telegram Mini App
    try:
        init = safe_parse_webapp_init_data(BOT_TOKEN, data.initData)
    except ValueError:
        raise HTTPException(status_code=403, detail="invalid init data")
    if init.user is None or time.time() - init.auth_date.timestamp() > 24 * 3600:
        raise HTTPException(status_code=403, detail="expired init data")

    full_name = " ".join(filter(None, [init.user.first_name, init.user.last_name])) or "Клиент"
    ok = await process_booking(
        bot,
        init.user.id,
        full_name,
        init.user.username,
        data.model_dump(exclude={"initData"}),
    )
    if not ok:
        log.error("Заявка от %s не доставлена мастеру", init.user.id)
        raise HTTPException(status_code=502, detail="delivery failed")
    return {"ok": True}
