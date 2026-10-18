#!/usr/bin/env python3
"""Check that the Telegram bot token from .env is valid."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


def main() -> int:
    load_dotenv(Path(__file__).with_name(".env"))
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: BOT_TOKEN is not set in .env")
        return 1

    url = f"https://api.telegram.org/bot{token}/getMe"
    request = urllib.request.Request(url, headers={"User-Agent": "telegram-bot-check/1.0"})

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Telegram API returned HTTP {exc.code}.")
        return 2
    except urllib.error.URLError as exc:
        print(f"ERROR: Network connection failed: {exc.reason}")
        return 3

    if not data.get("ok"):
        print(f"ERROR: Telegram API rejected the token: {data}")
        return 4

    bot = data.get("result", {})
    username = bot.get("username", "unknown")
    name = bot.get("first_name", "")
    bot_id = bot.get("id", "unknown")
    print("OK: Telegram bot token is valid.")
    print(f"Bot: {name} (@{username}), id={bot_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
