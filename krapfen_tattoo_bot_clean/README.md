# krapfen — Telegram-бот + Mini App

Бот отвечает клиентам по базовым вопросам (цена, уход, запись, референсы, работы),
остальное пересылает мастеру. Мастер отвечает **свайпом (Reply)** по пересланному
сообщению — ответ уходит клиенту от имени бота, а бот на это время замолкает
(`HANDOFF_HOURS`, по умолчанию 12 ч), чтобы не вмешиваться в живой диалог.
Заявки из Mini App приходят мастеру тем же способом.

Все тексты ответов — в `texts.py`, правила распознавания вопросов — в `bot.py` (`INTENTS`).

## Запуск на сервере 24/7 (Docker)

1. Арендуйте VPS с Ubuntu (самый дешёвый тариф подойдёт, лучше сервер в Европе).
2. Направьте домен (или бесплатный поддомен, например на duckdns.org) A-записью на IP сервера.
3. На сервере: `curl -fsSL https://get.docker.com | sh`
4. Загрузите папку проекта на сервер, например с вашего компьютера:
   `scp -r krapfen_bot root@IP_СЕРВЕРА:/opt/`
5. На сервере:
   ```bash
   cd /opt/krapfen_bot
   cp .env.example .env
   nano .env            # BOT_TOKEN, DOMAIN, WEBAPP_URL, ADMIN_IDS
   docker compose up -d --build
   docker compose logs -f bot     # должно появиться «Бот @... запущен»
   ```
6. **Закройте бота на своём компьютере** — два запущенных экземпляра с одним токеном конфликтуют.

Docker сам перезапускает контейнеры при падении и после перезагрузки сервера
(`restart: unless-stopped`).

## Узнать ADMIN_IDS
Мастер пишет боту `/id` — бот ответит числом. Его и вписывают в `ADMIN_IDS`
(несколько — через запятую).

## Обновление после правок
Загрузите изменённые файлы на сервер и выполните `docker compose up -d --build`.

## Полезные команды
- `docker compose ps` — состояние
- `docker compose logs --tail 100 bot` — логи бота
- `docker compose restart bot` — перезапуск

## Локально (для отладки)
```bash
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt
python bot.py                                      # бот
uvicorn server:app --port 8000                     # Mini App
```
