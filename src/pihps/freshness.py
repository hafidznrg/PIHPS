"""Freshness check (F3): apakah data di R2 masih segar?

    uv run python -m pihps.freshness [--notify failure|always|never]

Membaca `marts/_build.json` (ditulis pihps.transform saat publish) dan memeriksa:

1. **Data basi**: tanggal harga terbaru nasional pasar tradisional tertinggal lebih dari
   `--max-business-days` (default 3) hari kerja dari hari ini (WIB). Hari kerja = Senin-Jumat
   di luar libur nasional & cuti bersama (seed transform/seeds/hari_libur.csv), jadi libur
   panjang seperti Lebaran tidak memicu peringatan palsu.
2. **Build basi**: build terakhir lebih tua dari `--max-build-age-hours` (default 30), artinya
   workflow transform (atau extract yang memicunya) tidak berjalan.

Kode keluar: 0 segar, 1 basi, 3 error (mis. _build.json tidak terbaca).
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pihps.config import TZ_WIB
from pihps.extract import to_telegram_html

log = logging.getLogger("freshness")

BUILD_INFO_KEY = "marts/_build.json"
MAX_BUSINESS_DAYS = 3
MAX_BUILD_AGE_HOURS = 30
EXIT_OK, EXIT_STALE, EXIT_ERROR = 0, 1, 3
HOLIDAYS_CSV = Path(__file__).resolve().parents[2] / "transform/seeds/hari_libur.csv"


def load_holidays(path: Path = HOLIDAYS_CSV) -> set[date]:
    """Tanggal libur nasional + cuti bersama dari seed dbt (kosong bila file tidak ada)."""
    if not path.exists():
        log.warning("seed hari libur %s tidak ada; hanya akhir pekan yang dikecualikan", path)
        return set()
    with path.open() as fh:
        return {date.fromisoformat(r["tanggal"]) for r in csv.DictReader(fh)}


def business_days_between(start: date, end: date, holidays: Collection[date] = ()) -> int:
    """Jumlah hari kerja (Senin-Jumat, bukan libur) di (start, end]. 0 bila end <= start."""
    days = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.isoweekday() <= 5 and cur not in holidays:
            days += 1
    return days


@dataclass
class Freshness:
    ok: bool
    problems: list[str] = field(default_factory=list)
    latest_date: date | None = None
    lag_business_days: int | None = None
    build_age_hours: float | None = None


def evaluate(
    build_info: dict[str, Any],
    now: datetime,
    *,
    max_business_days: int = MAX_BUSINESS_DAYS,
    max_build_age_hours: float = MAX_BUILD_AGE_HOURS,
    holidays: Collection[date] = (),
) -> Freshness:
    res = Freshness(ok=True)
    today = now.astimezone(TZ_WIB).date()

    latest = (build_info.get("profile") or {}).get("terbaru_nasional_tradisional")
    if latest:
        res.latest_date = date.fromisoformat(str(latest)[:10])
        res.lag_business_days = business_days_between(res.latest_date, today, holidays)
        if res.lag_business_days > max_business_days:
            res.problems.append(
                f"data basi: harga nasional pasar tradisional terbaru {res.latest_date} "
                f"({res.lag_business_days} hari kerja lalu, batas {max_business_days})"
            )
    else:
        res.problems.append("tanggal data terbaru tidak tercatat di _build.json")

    built_at = build_info.get("built_at")
    if built_at:
        age = now - datetime.fromisoformat(built_at)
        res.build_age_hours = round(age.total_seconds() / 3600, 1)
        if res.build_age_hours > max_build_age_hours:
            res.problems.append(
                f"build basi: transform terakhir {res.build_age_hours} jam lalu "
                f"(batas {max_build_age_hours} jam) — cek workflow extract/transform"
            )
    else:
        res.problems.append("waktu build tidak tercatat di _build.json")

    res.ok = not res.problems
    return res


def format_report(res: Freshness) -> str:
    head = "✅ PIHPS freshness: data segar" if res.ok else "⚠️ PIHPS freshness: data basi"

    def show(v: object) -> str:
        return "-" if v is None else str(v)

    lines = [
        head,
        f"Harga terbaru (nasional, tradisional): {show(res.latest_date)} "
        f"({show(res.lag_business_days)} hari kerja lalu)",
        f"Build terakhir: {show(res.build_age_hours)} jam lalu",
    ]
    lines += [f"• {p}" for p in res.problems]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        prog="python -m pihps.freshness", description=__doc__.split("\n")[0]
    )
    ap.add_argument("--max-business-days", type=int, default=MAX_BUSINESS_DAYS)
    ap.add_argument("--max-build-age-hours", type=float, default=MAX_BUILD_AGE_HOURS)
    ap.add_argument("--notify", choices=["failure", "always", "never"], default="failure")
    args = ap.parse_args(argv)

    from pihps.notify import send_telegram

    try:
        from pihps.config import R2Config
        from pihps.storage import R2Storage

        info = R2Storage(R2Config.from_env()).get_json(BUILD_INFO_KEY)
        res = evaluate(
            info,
            datetime.now(UTC),
            max_business_days=args.max_business_days,
            max_build_age_hours=args.max_build_age_hours,
            holidays=load_holidays(),
        )
    except Exception as exc:  # noqa: BLE001 - tidak bisa memeriksa = juga harus terdengar
        log.exception("freshness check gagal")
        report = f"❌ PIHPS freshness: tidak bisa diperiksa\n{type(exc).__name__}: {exc}"[:500]
        code = EXIT_ERROR
    else:
        report = format_report(res)
        code = EXIT_OK if res.ok else EXIT_STALE

    print(report)
    if args.notify == "always" or (args.notify == "failure" and code != EXIT_OK):
        try:
            send_telegram(to_telegram_html(report))
        except Exception as exc:  # noqa: BLE001
            log.error("notifikasi Telegram gagal: %s", exc)
    return code


if __name__ == "__main__":
    sys.exit(main())
