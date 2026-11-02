"""Backfill historis: rencana job matriks dan ringkasan akhir.

Backfill dijalankan oleh workflow `backfill` sebagai matriks `jenis_pasar x tahun`; setiap job
memanggil `python -m pihps.extract --start .. --end ..` (otomatis dipecah per bulan).

    python -m pihps.backfill plan --first 2017-06-01 --last 2026-10-31 --price-types 1,2,3,4
    python -m pihps.backfill summary --plan plan.json --manifests manifests/ [--notify]

Lihat docs/PLAN.md (keputusan backfill) dan docs/raw-layout.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from pihps.config import PRICE_TYPES

log = logging.getLogger("backfill")

DATA_START = date(2017, 6, 1)  # awal data PIHPS (probe F0)


def plan_jobs(first: date, last: date, price_types: list[int]) -> list[dict[str, Any]]:
    """Satu job per (jenis pasar, tahun kalender), dipotong ke [first, last].

    Urutan: jenis pasar menaik (tradisional dulu), tahun menurun (data terbaru dulu), supaya
    bila backfill terhenti, bagian yang paling berguna untuk web sudah ada.
    """
    if last < first:
        raise ValueError(f"last ({last}) sebelum first ({first})")
    jobs: list[dict[str, Any]] = []
    for pt in price_types:
        slug = PRICE_TYPES[pt]
        for year in range(last.year, first.year - 1, -1):
            start = max(first, date(year, 1, 1))
            end = min(last, date(year, 12, 31))
            jobs.append(
                {
                    "name": f"{slug}-{year}",
                    "price_type": pt,
                    "jenis_pasar": slug,
                    "year": year,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
            )
    return jobs


def _job_key(price_type: int | str, start: str, end: str) -> tuple[str, str, str]:
    return (str(price_type), start, end)


def summarize(
    jobs: list[dict[str, Any]], manifests: list[dict[str, Any]]
) -> tuple[str, bool, dict[str, Any]]:
    """Gabungkan manifest semua job. Kembalikan (teks laporan, semua_ok, angka total)."""
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for m in manifests:
        p = m["params"]
        for pt in p["price_types"]:
            by_key[_job_key(pt, p["start_date"], p["end_date"])] = m

    totals = {
        "jobs": len(jobs),
        "success": 0,
        "failed": 0,
        "missing": 0,
        "requests": 0,
        "failed_requests": 0,
        "empty": 0,
        "records": 0,
        "bytes": 0,
        "duration_s": 0.0,
    }
    problems: list[str] = []
    empty_by_slug: dict[str, int] = {}
    for job in jobs:
        m = by_key.get(_job_key(job["price_type"], job["start"], job["end"]))
        if m is None:
            totals["missing"] += 1
            problems.append(f"• {job['name']}: tidak ada manifest (dibatalkan/crash)")
            continue
        s = m["summary"]
        totals["success" if m["status"] == "success" else "failed"] += 1
        totals["requests"] += s["requests_total"]
        totals["failed_requests"] += s["failed"]
        empty = sum(s.get("grid_empty_by_level", {}).values())
        totals["empty"] += empty
        empty_by_slug[job["jenis_pasar"]] = empty_by_slug.get(job["jenis_pasar"], 0) + empty
        totals["records"] += s["records_total"]
        totals["bytes"] += s["bytes_total"]
        totals["duration_s"] += s["duration_s"]
        if m["status"] != "success":
            reasons = [sf["reason"] for sf in m.get("silent_failures", [])]
            if s.get("aborted"):
                reasons.append("aborted")
            if s["failed"]:
                reasons.append(f"{s['failed']} request gagal")
            problems.append(f"• {job['name']}: {'; '.join(reasons) or m['status']}")

    ok = totals["success"] == totals["jobs"]
    icon = "✅" if ok else "❌"
    hours = totals["duration_s"] / 3600
    lines = [
        f"{icon} PIHPS backfill ({totals['success']}/{totals['jobs']} job sukses)",
        f"Rentang {jobs[0]['start'] if jobs else '-'} … "
        f"{max((j['end'] for j in jobs), default='-')}",
        f"{totals['requests']} request, {totals['failed_requests']} gagal, "
        f"{totals['empty']} kosong, {totals['records']} record, "
        f"{totals['bytes'] / 1e6:.1f} MB mentah, {hours:.1f} jam",
    ]
    if empty_by_slug:
        lines.append("Kosong per jenis pasar: " + json.dumps(empty_by_slug))
    if totals["failed"] or totals["missing"]:
        lines.append(f"{totals['failed']} job gagal, {totals['missing']} tanpa manifest:")
        lines += problems[:15]
        if len(problems) > 15:
            lines.append(f"… dan {len(problems) - 15} lainnya")
    return "\n".join(lines), ok, totals


# ----------------------------------------------------------------------- CLI
def _price_types(s: str) -> list[int]:
    ids = [int(x) for x in s.split(",") if x.strip()]
    if not ids or any(i not in PRICE_TYPES for i in ids):
        raise argparse.ArgumentTypeError(f"price_type_id tidak dikenal: {s!r}")
    return ids


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m pihps.backfill")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="cetak matriks job sebagai JSON")
    p_plan.add_argument("--first", type=date.fromisoformat, default=DATA_START)
    p_plan.add_argument("--last", type=date.fromisoformat, required=True)
    p_plan.add_argument("--price-types", type=_price_types, default=list(PRICE_TYPES))

    p_sum = sub.add_parser("summary", help="gabungkan manifest semua job")
    p_sum.add_argument("--plan", type=Path, required=True, help="file JSON dari `plan`")
    p_sum.add_argument("--manifests", type=Path, required=True, help="direktori manifest")
    p_sum.add_argument("--notify", action="store_true", help="kirim ringkasan ke Telegram")

    args = ap.parse_args(argv)

    if args.cmd == "plan":
        if args.first < DATA_START:
            log.warning("--first %s sebelum awal data PIHPS %s", args.first, DATA_START)
        try:
            jobs = plan_jobs(args.first, args.last, args.price_types)
        except ValueError as exc:
            log.error("%s", exc)
            return 2
        print(json.dumps({"include": jobs}, separators=(",", ":")))
        return 0

    jobs = json.loads(args.plan.read_text())["include"]
    manifests = [json.loads(f.read_text()) for f in sorted(args.manifests.rglob("*.json"))]
    report, ok, totals = summarize(jobs, manifests)
    print(report)
    log.info("totals %s", json.dumps(totals))
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a") as fh:
            fh.write(f"## PIHPS backfill\n\n```\n{report}\n```\n")
    if args.notify:
        from pihps.extract import to_telegram_html
        from pihps.notify import send_telegram

        try:
            sent = send_telegram(to_telegram_html(report))
            log.info("notifikasi Telegram %s", "terkirim" if sent else "TIDAK terkirim")
        except Exception as exc:  # noqa: BLE001
            log.error("notifikasi Telegram gagal: %s", exc)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
