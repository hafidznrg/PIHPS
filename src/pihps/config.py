"""Konstanta dan konfigurasi dari environment variable."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

BASE_URL = "https://www.bi.go.id/hargapangan"
API_PREFIX = f"{BASE_URL}/WebSite/TabelHarga"

TZ_WIB = ZoneInfo("Asia/Jakarta")

# price_type_id -> slug jenis pasar.
# 1 terverifikasi dari HAR; 2-4 diasumsikan dari urutan menu, diverifikasi oleh probe.
PRICE_TYPES: dict[int, str] = {
    1: "pasar_tradisional",
    2: "pasar_modern",
    3: "pedagang_besar",
    4: "produsen",
}

# tipe_laporan yang aktif di UI (2 dan 3 dikomentari di source halaman).
REPORT_TYPES: dict[int, str] = {
    1: "harian",
    4: "mingguan",
    5: "bulanan",
}

USER_AGENT = (
    "pihps-data-pipeline/0.1 (+https://github.com/hafidznrg/pihps; "
    "portfolio project, data attributed to PIHPS Nasional - Bank Indonesia)"
)


@dataclass(frozen=True)
class R2Config:
    endpoint: str
    access_key_id: str
    secret_access_key: str
    bucket: str

    @classmethod
    def from_env(cls) -> R2Config:
        return cls(
            endpoint=os.environ["R2_ENDPOINT"].rstrip("/"),
            access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            bucket=os.environ["R2_BUCKET"],
        )


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str

    @classmethod
    def from_env(cls) -> TelegramConfig | None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return None
        return cls(bot_token=token, chat_id=chat)
