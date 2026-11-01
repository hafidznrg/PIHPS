"""Probe sekali jalan: uji asumsi tentang API PIHPS, R2, dan Telegram dari runner.

Jalankan: `uv run python -m pihps.probe`
Hasil: ringkasan di stdout, $GITHUB_STEP_SUMMARY (jika ada), probe_result.json,
objek di R2 `_probe/<run_id>/result.json`, dan pesan Telegram.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from pihps.client import PihpsClient
from pihps.config import PRICE_TYPES, TZ_WIB, R2Config
from pihps.notify import send_telegram
from pihps.parse import grid_to_rows
from pihps.storage import R2Storage

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("probe")


class Probe:
    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}

    def check(self, name: str, fn: Callable[[], Any]) -> Any:
        t0 = time.monotonic()
        try:
            detail = fn()
            self.results[name] = {
                "ok": True,
                "secs": round(time.monotonic() - t0, 2),
                "detail": detail,
            }
            log.info("OK   %s (%.1fs): %s", name, time.monotonic() - t0, str(detail)[:300])
            return detail
        except Exception as exc:  # noqa: BLE001 - probe mencatat semua kegagalan
            self.results[name] = {
                "ok": False,
                "secs": round(time.monotonic() - t0, 2),
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=3),
            }
            log.error("FAIL %s: %s", name, exc)
            return None


def summarize_grid(payload: dict[str, Any]) -> dict[str, Any]:
    rows = grid_to_rows(payload)
    dates = sorted({r.tanggal for r in rows})
    non_null = [r for r in rows if r.harga is not None]
    return {
        "records": len(payload.get("data", [])),
        "rows": len(rows),
        "non_null": len(non_null),
        "first_date": dates[0].isoformat() if dates else None,
        "last_date": dates[-1].isoformat() if dates else None,
        "n_dates": len(dates),
        "sample": [
            {"tanggal": r.tanggal.isoformat(), "nama": r.nama_komoditas, "harga": r.harga}
            for r in non_null[:3]
        ],
    }


def main() -> int:
    run_id = datetime.now(TZ_WIB).strftime("%Y%m%dT%H%M%S")
    today = datetime.now(TZ_WIB).date()
    week_ago = today - timedelta(days=14)
    p = Probe()

    with PihpsClient(min_interval=1.5) as c:
        # 1. Referensi
        p.check("ref_price_types", lambda: c.ref_price_types()["data"])
        p.check("ref_commodities_count", lambda: len(c.ref_commodities()["data"]))
        provinces = p.check("ref_provinces", lambda: c.ref_provinces()["data"]) or []

        # 2. Harga nasional untuk tiap jenis pasar
        for pt, slug in PRICE_TYPES.items():
            p.check(
                f"grid_nasional_{slug}",
                lambda pt=pt: summarize_grid(
                    c.grid_daerah(price_type_id=pt, start_date=week_ago, end_date=today)
                ),
            )

        # 3. Drill-down: provinsi -> kab/kota -> pasar (DKI Jakarta = 13, pasar tradisional)
        prov_id = 13
        regencies = p.check("ref_regencies_dki", lambda: c.ref_regencies(1, prov_id)["data"]) or []
        p.check(
            "grid_provinsi_dki",
            lambda: summarize_grid(
                c.grid_daerah(
                    price_type_id=1, start_date=week_ago, end_date=today, province_id=prov_id
                )
            ),
        )
        if regencies:
            reg_id = regencies[0].get("id")
            p.check("ref_markets_first_regency", lambda: c.ref_markets(1, reg_id)["data"][:10])
            p.check(
                "grid_regency_first",
                lambda: summarize_grid(
                    c.grid_daerah(
                        price_type_id=1,
                        start_date=week_ago,
                        end_date=today,
                        province_id=prov_id,
                        regency_id=reg_id,
                    )
                ),
            )

        # 4. Bisakah multi-provinsi dalam satu request (comma-separated)?
        p.check(
            "grid_multi_province_13_12",
            lambda: summarize_grid(
                c.grid_daerah(
                    price_type_id=1, start_date=week_ago, end_date=today, province_id="13,12"
                )
            ),
        )

        # 5. Kedalaman historis & batas rentang tanggal (pasar tradisional, nasional)
        for label, start, end in [
            ("2017_06", date(2017, 6, 1), date(2017, 6, 30)),
            ("2018_01", date(2018, 1, 1), date(2018, 1, 31)),
            ("2020_01", date(2020, 1, 1), date(2020, 1, 31)),
            ("2023_07", date(2023, 7, 1), date(2023, 7, 31)),
            ("range_1y", today - timedelta(days=365), today),
        ]:
            p.check(
                f"history_{label}",
                lambda s=start, e=end: summarize_grid(
                    c.grid_daerah(price_type_id=1, start_date=s, end_date=e)
                ),
            )

        # 6. Laporan mingguan (tipe_laporan=4)
        p.check(
            "grid_mingguan",
            lambda: summarize_grid(
                c.grid_daerah(
                    price_type_id=1,
                    start_date=today - timedelta(days=60),
                    end_date=today,
                    tipe_laporan=4,
                )
            ),
        )

    # 7. R2 tulis & baca balik
    result_doc = {"run_id": run_id, "results": p.results, "n_provinces": len(provinces)}
    key = f"_probe/{run_id}/result.json"

    def r2_roundtrip() -> dict[str, Any]:
        r2 = R2Storage(R2Config.from_env())
        size = r2.put_json(key, result_doc)
        back = r2.get_json(key)
        assert back["run_id"] == run_id
        return {"key": key, "bytes": size}

    p.check("r2_roundtrip", r2_roundtrip)

    # Output
    with open("probe_result.json", "w") as fh:
        json.dump({"run_id": run_id, "results": p.results}, fh, indent=2, default=str)

    ok = sum(r["ok"] for r in p.results.values())
    total = len(p.results)
    lines = [f"<b>PIHPS probe {run_id}</b>", f"{ok}/{total} cek lolos", ""]
    for name, r in p.results.items():
        mark = "✅" if r["ok"] else "❌"
        extra = ""
        if r["ok"] and isinstance(r["detail"], dict) and "rows" in r["detail"]:
            d = r["detail"]
            extra = f" rows={d['rows']} {d['first_date']}→{d['last_date']}"
        elif not r["ok"]:
            extra = f" {r['error'][:80]}"
        lines.append(f"{mark} {name}{extra}")
    msg = "\n".join(lines)
    print(msg)

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as fh:
            fh.write(
                "## PIHPS probe\n\n```\n" + msg.replace("<b>", "").replace("</b>", "") + "\n```\n"
            )

    def telegram() -> bool:
        if not send_telegram(msg):
            raise RuntimeError("gagal kirim (cek secret TELEGRAM_*)")
        return True

    p.check("telegram", telegram)

    core_ok = p.results.get("grid_nasional_pasar_tradisional", {}).get("ok", False)
    return 0 if core_ok else 1


if __name__ == "__main__":
    sys.exit(main())
