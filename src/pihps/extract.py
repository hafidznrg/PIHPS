"""Extractor harian PIHPS -> raw zone di Cloudflare R2.

Jalankan: `uv run python -m pihps.extract` (default: 7 hari terakhir s.d. hari ini, WIB)
          `uv run python -m pihps.extract --start 2017-06-01 --end 2017-12-31` (backfill)
          `uv run python -m pihps.extract --local-dir data/raw` (tanpa R2, untuk dev)

Respons API disimpan APA ADANYA (byte persis dari server, di-gzip) dengan layout:

    raw/pihps/endpoint=<endpoint>/jenis_pasar=<slug>/ingest_date=YYYY-MM-DD/
        run_id=<YYYYMMDDTHHMMSS>/<level>=<id>.json.gz

Snapshot referensi ditulis di `raw/pihps/endpoint=ref_*/...` dan manifest run di
`raw/pihps/_manifests/ingest_date=YYYY-MM-DD/run_id=<id>/_manifest.json`.
Lihat docs/raw-layout.md.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from pihps import __version__
from pihps.client import PihpsClient, PihpsError, RawResponse, grid_daerah_params
from pihps.config import PRICE_TYPES, TZ_WIB, R2Config
from pihps.parse import grid_to_rows

log = logging.getLogger("extract")

RAW_PREFIX = "raw/pihps"
LEVELS = ("nasional", "provinsi", "kabkota")
NATIONAL_ID = "all"
MIN_INTERVAL_S = 1.5
MAX_SINGLE_CHUNK_DAYS = 31
# Jenis pasar acuan untuk deteksi silent failure (lihat check_silent_failure).
SENTINEL_PRICE_TYPE = 1
EXPECTED_PROVINCES = 34


# --------------------------------------------------------------------------- sink
class Sink(Protocol):
    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = ...,
        metadata: dict[str, str] | None = ...,
    ) -> int: ...

    def put_json(self, key: str, obj: Any) -> int: ...


class LocalSink:
    """Tulis ke direktori lokal dengan key yang sama seperti di R2 (untuk dev/test)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> int:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return len(body)

    def put_json(self, key: str, obj: Any) -> int:
        body = json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode()
        return self.put_bytes(key, body, content_type="application/json")


# ------------------------------------------------------------------ util murni
def split_range(start: date, end: date) -> list[tuple[date, date]]:
    """Rentang <= 31 hari tetap satu potong; lebih dari itu dipecah per bulan kalender.

    Rentang 1 tahun timeout di server (lihat docs/api-notes.md), 1 bulan aman.
    """
    if end < start:
        raise ValueError(f"end ({end}) sebelum start ({start})")
    if (end - start).days + 1 <= MAX_SINGLE_CHUNK_DAYS:
        return [(start, end)]
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        next_month = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        chunk_end = min(next_month - timedelta(days=1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def object_key(
    *,
    endpoint: str,
    ingest_date: date,
    run_id: str,
    level: str,
    level_id: str | int,
    jenis_pasar: str | None = None,
    chunk: tuple[date, date] | None = None,
) -> str:
    """Key objek raw. `chunk` hanya diisi bila run dipecah ke beberapa rentang (backfill)."""
    parts = [RAW_PREFIX, f"endpoint={endpoint}"]
    if jenis_pasar:
        parts.append(f"jenis_pasar={jenis_pasar}")
    parts += [f"ingest_date={ingest_date.isoformat()}", f"run_id={run_id}"]
    suffix = f"_{chunk[0]:%Y%m%d}-{chunk[1]:%Y%m%d}" if chunk else ""
    parts.append(f"{level}={level_id}{suffix}.json.gz")
    return "/".join(parts)


def manifest_key(ingest_date: date, run_id: str) -> str:
    return (
        f"{RAW_PREFIX}/_manifests/ingest_date={ingest_date.isoformat()}"
        f"/run_id={run_id}/_manifest.json"
    )


def count_records(payload: dict[str, Any]) -> int:
    """Jumlah record bermakna di `data` (respons kosong PIHPS berbentuk `[{}]`)."""
    data = payload.get("data")
    if not isinstance(data, list):
        return 0
    return sum(1 for rec in data if rec)


def check_silent_failure(payload: dict[str, Any]) -> str | None:
    """Kembalikan alasan bila respons nasional terlihat 'sukses' tapi sebenarnya kosong.

    HTTP 200 dengan `{"data": [{}]}`, tanpa kolom tanggal, atau semua harga kosong
    dianggap gagal: harga nasional pasar tradisional seharusnya selalu ada untuk
    rentang yang memuat minimal satu hari kerja.
    """
    if count_records(payload) == 0:
        return "respons tanpa record"
    try:
        rows = grid_to_rows(payload)
    except (KeyError, ValueError, TypeError) as exc:
        return f"respons tidak bisa diparse: {exc}"
    if not rows:
        return "respons tanpa kolom tanggal"
    if all(r.harga is None for r in rows):
        return f"semua {len(rows)} nilai harga kosong"
    return None


def git_sha() -> str | None:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


# ------------------------------------------------------------------- extractor
@dataclass
class RunParams:
    start: date
    end: date
    price_types: list[int]
    levels: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
            "price_types": {pt: PRICE_TYPES[pt] for pt in self.price_types},
            "levels": self.levels,
            "tipe_laporan": 1,
        }


@dataclass
class Extractor:
    client: PihpsClient
    sink: Sink
    params: RunParams
    run_id: str
    ingest_date: date
    files: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    silent_failures: list[dict[str, Any]] = field(default_factory=list)
    provinces: list[dict[str, Any]] = field(default_factory=list)
    _written: set[str] = field(default_factory=set)

    # ----------------------------------------------------------- satu request
    def fetch_and_store(
        self,
        *,
        endpoint_name: str,
        api_endpoint: str,
        api_params: dict[str, Any],
        level: str,
        level_id: str | int,
        jenis_pasar: str | None = None,
        chunk: tuple[date, date] | None = None,
        context: dict[str, Any] | None = None,
    ) -> RawResponse | None:
        """Ambil satu respons, simpan apa adanya, catat ke manifest. Tidak pernah raise."""
        key = object_key(
            endpoint=endpoint_name,
            ingest_date=self.ingest_date,
            run_id=self.run_id,
            level=level,
            level_id=level_id,
            jenis_pasar=jenis_pasar,
            chunk=chunk,
        )
        entry: dict[str, Any] = {
            "path": key,
            "endpoint": api_endpoint,
            "jenis_pasar": jenis_pasar,
            "level": level,
            "level_id": level_id,
            **(context or {}),
            "url": None,
            "params": api_params,
            "http_status": None,
            "fetched_at": None,
            "bytes": None,
            "gz_bytes": None,
            "sha256": None,
            "records": None,
            "ok": False,
            "error": None,
        }
        self.files.append(entry)

        if key in self._written:
            entry["path"] = None
            entry["error"] = f"key duplikat dalam satu run: {key}"
            log.error("FAIL %s", entry["error"])
            return None

        try:
            raw = self.client.fetch(api_endpoint, api_params)
        except PihpsError as exc:
            entry.update(url=exc.url, http_status=exc.status_code, error=str(exc))
            entry["fetched_at"] = datetime.now(UTC).isoformat()
            log.error("FAIL %s %s=%s: %s", api_endpoint, level, level_id, exc)
            return None

        sha = hashlib.sha256(raw.body).hexdigest()
        gz = gzip.compress(raw.body, mtime=0)
        entry.update(
            url=raw.url,
            http_status=raw.status_code,
            fetched_at=raw.fetched_at.isoformat(),
            bytes=len(raw.body),
            gz_bytes=len(gz),
            sha256=sha,
            records=count_records(raw.payload),
        )
        try:
            self.sink.put_bytes(
                key,
                gz,
                content_type="application/gzip",
                metadata={"sha256": sha, "run-id": self.run_id, "source-url": raw.url[:1024]},
            )
        except Exception as exc:  # noqa: BLE001 - kegagalan upload dicatat, run lanjut
            entry["error"] = f"upload gagal: {type(exc).__name__}: {exc}"
            log.error("FAIL upload %s: %s", key, exc)
            return raw

        self._written.add(key)
        entry["ok"] = True
        log.info("OK   %s (%d record, %d B)", key, entry["records"], len(raw.body))
        return raw

    # -------------------------------------------------------------- referensi
    def fetch_refs(self) -> dict[int, dict[int, list[dict[str, Any]]]]:
        """Snapshot referensi. Mengembalikan {price_type_id: {province_id: [regency, ...]}}."""
        for name, ep in [
            ("ref_price_type", "GetRefPriceType"),
            ("ref_commodity", "GetRefCommodityAndCategory"),
        ]:
            self.fetch_and_store(
                endpoint_name=name,
                api_endpoint=ep,
                api_params={},
                level="nasional",
                level_id=NATIONAL_ID,
            )

        provinces: list[dict[str, Any]] = []
        if {"provinsi", "kabkota"} & set(self.params.levels):
            raw = self.fetch_and_store(
                endpoint_name="ref_province",
                api_endpoint="GetRefProvince",
                api_params={},
                level="nasional",
                level_id=NATIONAL_ID,
            )
            if raw is not None:
                provinces = [p for p in raw.payload["data"] if p and "id" in p]
                if len(provinces) != EXPECTED_PROVINCES:
                    self.warn(
                        f"GetRefProvince mengembalikan {len(provinces)} provinsi "
                        f"(diharapkan {EXPECTED_PROVINCES})"
                    )
        self.provinces = provinces

        regencies: dict[int, dict[int, list[dict[str, Any]]]] = {}
        if "kabkota" in self.params.levels:
            for pt in self.params.price_types:
                regencies[pt] = {}
                for prov in provinces:
                    raw = self.fetch_and_store(
                        endpoint_name="ref_regency",
                        api_endpoint="GetRefRegency",
                        api_params={"price_type_id": pt, "ref_prov_id": prov["id"]},
                        level="provinsi",
                        level_id=prov["id"],
                        jenis_pasar=PRICE_TYPES[pt],
                        context={"province_id": prov["id"], "province_name": prov.get("name")},
                    )
                    if raw is not None:
                        regencies[pt][prov["id"]] = [
                            r for r in raw.payload["data"] if r and "id" in r
                        ]
        return regencies

    # ------------------------------------------------------------------ harga
    def fetch_grids(self, regencies: dict[int, dict[int, list[dict[str, Any]]]]) -> None:
        chunks = split_range(self.params.start, self.params.end)
        chunk_in_name = len(chunks) > 1
        for pt in self.params.price_types:
            slug = PRICE_TYPES[pt]
            for chunk in chunks:
                common = {
                    "endpoint_name": "grid_daerah",
                    "api_endpoint": "GetGridDataDaerah",
                    "jenis_pasar": slug,
                    "chunk": chunk if chunk_in_name else None,
                }

                def gp(
                    pt: int = pt, chunk: tuple[date, date] = chunk, **ids: Any
                ) -> dict[str, Any]:
                    return grid_daerah_params(
                        price_type_id=pt, start_date=chunk[0], end_date=chunk[1], **ids
                    )

                if "nasional" in self.params.levels:
                    raw = self.fetch_and_store(
                        **common, api_params=gp(), level="nasional", level_id=NATIONAL_ID
                    )
                    if pt == SENTINEL_PRICE_TYPE:
                        self._sentinel(raw, chunk)

                for prov in self.provinces if "provinsi" in self.params.levels else []:
                    self.fetch_and_store(
                        **common,
                        api_params=gp(province_id=prov["id"]),
                        level="provinsi",
                        level_id=prov["id"],
                        context={"province_id": prov["id"], "province_name": prov.get("name")},
                    )

                for prov_id, regs in regencies.get(pt, {}).items():
                    for reg in regs:
                        self.fetch_and_store(
                            **common,
                            api_params=gp(province_id=prov_id, regency_id=reg["id"]),
                            level="kabkota",
                            level_id=reg["id"],
                            context={
                                "province_id": prov_id,
                                "regency_id": reg["id"],
                                "regency_name": reg.get("name"),
                            },
                        )

    def _sentinel(self, raw: RawResponse | None, chunk: tuple[date, date]) -> None:
        if raw is None:
            return  # sudah tercatat sebagai file gagal
        if reason := check_silent_failure(raw.payload):
            item = {
                "check": f"grid_daerah nasional {PRICE_TYPES[SENTINEL_PRICE_TYPE]}",
                "start_date": chunk[0].isoformat(),
                "end_date": chunk[1].isoformat(),
                "reason": reason,
            }
            self.silent_failures.append(item)
            log.error("SILENT FAILURE %s", item)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        log.warning(msg)

    # -------------------------------------------------------------------- run
    def run(self) -> dict[str, Any]:
        t0 = time.monotonic()
        started_at = datetime.now(UTC)
        try:
            regencies = self.fetch_refs()
            self.fetch_grids(regencies)
        except Exception as exc:  # noqa: BLE001 - bug tak terduga tetap menghasilkan manifest
            log.exception("run berhenti karena error tak terduga")
            self.warn(f"run berhenti: {type(exc).__name__}: {exc}")
            aborted = True
        else:
            aborted = False

        failed = [f for f in self.files if not f["ok"]]
        status = "failed" if (failed or self.silent_failures or aborted) else "success"
        return {
            "run_id": self.run_id,
            "ingest_date": self.ingest_date.isoformat(),
            "scraper_version": __version__,
            "git_sha": git_sha(),
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "params": self.params.as_dict(),
            "summary": {
                "requests_total": len(self.files),
                "http_attempts": self.client.n_requests,
                "succeeded": len(self.files) - len(failed),
                "failed": len(failed),
                "records_total": sum(f["records"] or 0 for f in self.files),
                "bytes_total": sum(f["bytes"] or 0 for f in self.files),
                "duration_s": round(time.monotonic() - t0, 1),
                "silent_failures": len(self.silent_failures),
                "aborted": aborted,
                "by_endpoint": _count_by(self.files),
            },
            "silent_failures": self.silent_failures,
            "warnings": self.warnings,
            "failed_files": [
                {k: f[k] for k in ("endpoint", "jenis_pasar", "level", "level_id", "error")}
                for f in failed
            ],
            "files": self.files,
        }


def _count_by(files: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for f in files:
        name = f"{f['endpoint']}/{f['jenis_pasar'] or '-'}/{f['level']}"
        bucket = out.setdefault(name, {"ok": 0, "failed": 0})
        bucket["ok" if f["ok"] else "failed"] += 1
    return out


# ----------------------------------------------------------------- pelaporan
def format_report(manifest: dict[str, Any], manifest_location: str) -> str:
    s = manifest["summary"]
    p = manifest["params"]
    icon = "✅" if manifest["status"] == "success" else "❌"
    lines = [
        f"{icon} <b>PIHPS extract {manifest['run_id']}</b> ({manifest['status']})",
        f"Rentang {p['start_date']} → {p['end_date']}",
        f"{s['succeeded']}/{s['requests_total']} request OK, {s['failed']} gagal, "
        f"{s['records_total']} record, {s['duration_s']}s",
    ]
    for sf in manifest["silent_failures"]:
        lines.append(f"⚠️ silent failure: {sf['check']} {sf['start_date']}: {sf['reason']}")
    for w in manifest["warnings"][:5]:
        lines.append(f"⚠️ {w}")
    for f in manifest["failed_files"][:10]:
        lines.append(
            f"• {f['endpoint']} {f['jenis_pasar'] or ''} {f['level']}={f['level_id']}: "
            f"{(f['error'] or '')[:100]}"
        )
    if len(manifest["failed_files"]) > 10:
        lines.append(f"… dan {len(manifest['failed_files']) - 10} lainnya")
    lines.append(f"Manifest: {manifest_location}")
    return "\n".join(lines)


# ----------------------------------------------------------------------- CLI
def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_price_types(s: str) -> list[int]:
    ids = [int(x) for x in s.split(",") if x.strip()]
    unknown = [i for i in ids if i not in PRICE_TYPES]
    if unknown or not ids:
        raise argparse.ArgumentTypeError(f"price_type_id tidak dikenal: {unknown or s!r}")
    return ids


def _parse_levels(s: str) -> list[str]:
    levels = [x.strip() for x in s.split(",") if x.strip()]
    unknown = [lv for lv in levels if lv not in LEVELS]
    if unknown or not levels:
        raise argparse.ArgumentTypeError(f"level tidak dikenal: {unknown or s!r}")
    return levels


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m pihps.extract", description=__doc__.split("\n")[0])
    ap.add_argument("--start", type=_parse_date, help="YYYY-MM-DD (default: end - days + 1)")
    ap.add_argument("--end", type=_parse_date, help="YYYY-MM-DD (default: hari ini, WIB)")
    ap.add_argument("--days", type=int, default=7, help="panjang rentang default (hari)")
    ap.add_argument(
        "--price-types",
        type=_parse_price_types,
        default=list(PRICE_TYPES),
        help="price_type_id dipisah koma (default: 1,2,3,4)",
    )
    ap.add_argument(
        "--levels",
        type=_parse_levels,
        default=list(LEVELS),
        help="nasional,provinsi,kabkota (default: semua)",
    )
    ap.add_argument("--local-dir", type=Path, help="tulis ke direktori lokal, bukan R2 (untuk dev)")
    ap.add_argument(
        "--min-interval",
        type=float,
        default=MIN_INTERVAL_S,
        help=f"jeda minimum antar-request, detik (>= {MIN_INTERVAL_S})",
    )
    ap.add_argument(
        "--manifest-out",
        type=Path,
        default=Path("extract_manifest.json"),
        help="salinan lokal manifest (untuk artifact CI)",
    )
    ap.add_argument(
        "--notify",
        choices=["failure", "always", "never"],
        default="failure",
        help="kirim ringkasan ke Telegram (default: hanya saat gagal)",
    )
    return ap


def resolve_range(
    start: date | None, end: date | None, days: int, today: date
) -> tuple[date, date]:
    end = end or today
    start = start or end - timedelta(days=days - 1)
    if start > end:
        raise ValueError(f"--start ({start}) setelah --end ({end})")
    return start, end


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    if args.min_interval < MIN_INTERVAL_S:
        log.error("--min-interval minimal %.1f detik (sopan ke server)", MIN_INTERVAL_S)
        return 2

    now = datetime.now(TZ_WIB)
    run_id = now.strftime("%Y%m%dT%H%M%S")
    try:
        start, end = resolve_range(args.start, args.end, args.days, now.date())
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    params = RunParams(start, end, args.price_types, args.levels)

    if args.local_dir:
        sink: Sink = LocalSink(args.local_dir)
        location_prefix = f"{args.local_dir}/"
    else:
        from pihps.storage import R2Storage

        cfg = R2Config.from_env()
        sink = R2Storage(cfg)
        location_prefix = f"r2://{cfg.bucket}/"

    log.info("run_id=%s rentang %s → %s, params=%s", run_id, start, end, params.as_dict())
    with PihpsClient(min_interval=args.min_interval) as client:
        manifest = Extractor(client, sink, params, run_id, now.date()).run()

    mkey = manifest_key(now.date(), run_id)
    manifest_ok = True
    try:
        sink.put_json(mkey, manifest)
    except Exception as exc:  # noqa: BLE001
        log.error("gagal menulis manifest ke %s: %s", mkey, exc)
        manifest_ok = False
    args.manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))

    report = format_report(manifest, location_prefix + mkey)
    print(report)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a") as fh:
            plain = report.replace("<b>", "").replace("</b>", "")
            fh.write(f"## PIHPS extract\n\n```\n{plain}\n```\n")

    ok = manifest["status"] == "success" and manifest_ok
    if args.notify == "always" or (args.notify == "failure" and not ok):
        from pihps.notify import send_telegram

        try:
            send_telegram(report)
        except Exception as exc:  # noqa: BLE001 - notifikasi tidak boleh mengubah exit code
            log.error("notifikasi Telegram gagal: %s", exc)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
