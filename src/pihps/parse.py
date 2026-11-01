"""Parser respons PIHPS: format lebar (kolom per tanggal) -> baris panjang."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

_DATE_KEY = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_MISSING = {"", "-", "0", None}


@dataclass(frozen=True)
class PriceRow:
    tanggal: date
    nama_komoditas: str
    level: int  # 1 = kategori (agregat), 2 = komoditas
    harga: int | None


def parse_price(value: Any) -> int | None:
    """'16,450' -> 16450; '-' / '' / None -> None."""
    if value in _MISSING:
        return None
    if isinstance(value, int | float):
        return int(value) or None
    cleaned = str(value).strip().replace(",", "").replace(".", "")
    if cleaned in _MISSING:
        return None
    if not cleaned.isdigit():
        raise ValueError(f"Format harga tak dikenal: {value!r}")
    return int(cleaned) or None


def date_columns(record: dict[str, Any]) -> list[str]:
    return [k for k in record if _DATE_KEY.match(k)]


def grid_to_rows(payload: dict[str, Any]) -> list[PriceRow]:
    rows: list[PriceRow] = []
    for rec in payload.get("data", []):
        if not rec:  # respons kosong berbentuk [{}]
            continue
        name = str(rec["name"]).strip()
        level = int(rec.get("level", 2))
        for key in date_columns(rec):
            tanggal = datetime.strptime(key, "%d/%m/%Y").date()
            rows.append(PriceRow(tanggal, name, level, parse_price(rec[key])))
    return rows
