"""Notifikasi Telegram."""

from __future__ import annotations

import logging

import httpx

from pihps.config import TelegramConfig

log = logging.getLogger(__name__)


def send_telegram(text: str, cfg: TelegramConfig | None = None) -> bool:
    cfg = cfg or TelegramConfig.from_env()
    if cfg is None:
        log.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID tidak di-set, notifikasi dilewati")
        return False
    resp = httpx.post(
        f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage",
        json={
            "chat_id": cfg.chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        log.error("Telegram gagal: HTTP %s %s", resp.status_code, resp.text[:200])
        return False
    return True
