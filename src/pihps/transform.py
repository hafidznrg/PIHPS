"""Transformasi F2: raw (R2) -> dbt-duckdb -> staging & marts Parquet (R2).

    uv run python -m pihps.transform run --publish            # sync + build + publish (CI)
    uv run python -m pihps.transform run --source local --raw-dir data   # dev, tanpa R2
    uv run python -m pihps.transform sync --raw-dir data      # hanya salin raw dari R2
    uv run python -m pihps.transform build --raw-dir data     # hanya dbt build

Alur:
1. **sync**: salin raw dari R2 ke disk (`<raw-dir>/raw/pihps/...`, key sama persis) LEWAT
   MANIFEST: daftar `_manifests/`, lalu unduh hanya file `ok: true` yang tercatat di manifest
   (file harga tanpa record dilewati). Inkremental: file yang sudah ada di disk dengan ukuran
   sama tidak diunduh ulang (raw immutable), sehingga cache Actions membuat run harian cepat.
2. **build**: `dbt build` (seed, model, tes) di `transform/` dengan DuckDB; model staging &
   marts ditulis sebagai Parquet ke `<out-dir>/staging/...` dan `<out-dir>/marts/...`.
3. **publish** (hanya bila build tanpa error): unggah `<out-dir>` ke R2 dengan key yang sama
   lalu hapus objek basi di prefix yang sama, sehingga isi R2 = hasil build terakhir.

Lihat docs/PLAN.md (F2) dan transform/README.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pihps.extract import RAW_PREFIX, git_sha, to_telegram_html

log = logging.getLogger("transform")

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = REPO_ROOT / "transform"
MANIFEST_PREFIX = f"{RAW_PREFIX}/_manifests/"
GRID_ENDPOINT = "GetGridDataDaerah"
# Prefix keluaran yang dikelola transform. Publish menyinkronkan persis prefix ini.
OUTPUT_PREFIXES = ("staging/", "marts/")
BUILD_INFO_KEY = "marts/_build.json"
DOWNLOAD_WORKERS = 16

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_ABORTED = 0, 1, 2, 3


# --------------------------------------------------------------------- store
class RemoteStore(Protocol):
    """Subset R2Storage yang dipakai di sini (memudahkan tes dengan store tiruan)."""

    def list_objects(self, prefix: str) -> list[dict[str, Any]]: ...
    def download_file(self, key: str, path: str) -> None: ...
    def upload_file(self, key: str, path: str, *, content_type: str) -> None: ...
    def delete_keys(self, keys: list[str]) -> None: ...


def wanted_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """File raw yang perlu dibaca staging dari satu manifest.

    Hanya `ok: true` (tersimpan utuh). Respons harga tanpa record (`[{}]`) dilewati karena
    tidak menghasilkan baris; respons referensi selalu diambil (snapshot dimensi).
    """
    out = []
    for f in manifest.get("files", []):
        if not f.get("ok") or not f.get("path"):
            continue
        if f.get("endpoint") == GRID_ENDPOINT and not f.get("records"):
            continue
        out.append(f)
    return out


@dataclass
class SyncStats:
    manifests: int = 0
    manifests_downloaded: int = 0
    files_wanted: int = 0
    files_downloaded: int = 0
    files_cached: int = 0
    files_missing: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["files_missing"] = len(self.files_missing)
        d["files_missing_sample"] = self.files_missing[:10]
        return d


def _is_cached(path: Path, size: int | None) -> bool:
    return path.exists() and (size is None or path.stat().st_size == size)


def sync_raw(store: RemoteStore, raw_dir: Path, *, workers: int = DOWNLOAD_WORKERS) -> SyncStats:
    """Salin manifest + file raw yang tercatat di manifest ke `raw_dir` (inkremental)."""
    t0 = time.monotonic()
    stats = SyncStats()

    def fetch(key: str, size: int | None) -> bool:
        path = raw_dir / key
        if _is_cached(path, size):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        store.download_file(key, str(tmp))
        tmp.replace(path)
        return True

    manifest_objs = [
        o for o in store.list_objects(MANIFEST_PREFIX) if o["Key"].endswith("_manifest.json")
    ]
    stats.manifests = len(manifest_objs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        downloaded = pool.map(lambda o: fetch(o["Key"], o.get("Size")), manifest_objs)
        stats.manifests_downloaded = sum(downloaded)

    wanted: dict[str, int | None] = {}
    for o in manifest_objs:
        manifest = json.loads((raw_dir / o["Key"]).read_text())
        for f in wanted_files(manifest):
            wanted[f["path"]] = f.get("gz_bytes")
    stats.files_wanted = len(wanted)

    def fetch_safe(item: tuple[str, int | None]) -> str:
        key, size = item
        try:
            return "downloaded" if fetch(key, size) else "cached"
        except Exception as exc:  # noqa: BLE001 - file hilang dicatat, bukan menghentikan run
            log.warning("gagal mengunduh %s: %s", key, exc)
            stats.files_missing.append(key)
            return "missing"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcome = Counter(pool.map(fetch_safe, wanted.items()))
    stats.files_downloaded = outcome["downloaded"]
    stats.files_cached = outcome["cached"]
    stats.duration_s = round(time.monotonic() - t0, 1)
    log.info("sync %s", json.dumps(stats.as_dict()))
    return stats


# --------------------------------------------------------------------- build
@dataclass
class BuildResult:
    success: bool
    counts: dict[str, int]
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    duration_s: float

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def reset_output(out_dir: Path) -> None:
    """Kosongkan keluaran lama agar partisi basi tidak ikut terpublish."""
    for prefix in OUTPUT_PREFIXES:
        shutil.rmtree(out_dir / prefix, ignore_errors=True)
        (out_dir / prefix).mkdir(parents=True, exist_ok=True)


def summarize_run_results(path: Path) -> tuple[dict[str, int], list[dict], list[dict]]:
    results = json.loads(path.read_text())["results"]
    counts = Counter(r["status"] for r in results)
    pick = ("unique_id", "status", "failures", "message")

    def short(r: dict[str, Any]) -> dict[str, Any]:
        d = {k: r.get(k) for k in pick}
        d["unique_id"] = d["unique_id"].split(".", 2)[-1]
        return d

    warnings = [short(r) for r in results if r["status"] == "warn"]
    errors = [short(r) for r in results if r["status"] in ("error", "fail")]
    return dict(counts), warnings, errors


def dbt_build(
    raw_dir: Path,
    out_dir: Path,
    db_path: Path,
    *,
    extra_args: Iterable[str] = (),
) -> BuildResult:
    from dbt.cli.main import dbtRunner

    t0 = time.monotonic()
    raw_dir, out_dir, db_path = raw_dir.resolve(), out_dir.resolve(), db_path.resolve()
    reset_output(out_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)  # selalu build penuh dari raw
    os.environ["PIHPS_DUCKDB_PATH"] = str(db_path)
    target = DBT_PROJECT_DIR / "target"
    dbt_vars = {"raw_root": raw_dir.as_posix(), "out_root": out_dir.as_posix()}
    args = [
        "build",
        "--project-dir",
        str(DBT_PROJECT_DIR),
        "--profiles-dir",
        str(DBT_PROJECT_DIR),
        "--target-path",
        str(target),
        "--log-path",
        str(DBT_PROJECT_DIR / "logs"),
        "--vars",
        json.dumps(dbt_vars),
        *extra_args,
    ]
    log.info("dbt %s", " ".join(args))
    res = dbtRunner().invoke(args)
    run_results = target / "run_results.json"
    if run_results.exists():
        counts, warnings, errors = summarize_run_results(run_results)
    else:
        counts, warnings, errors = {}, [], [{"unique_id": "dbt", "message": str(res.exception)}]
    return BuildResult(
        success=bool(res.success),
        counts=counts,
        warnings=warnings,
        errors=errors,
        duration_s=round(time.monotonic() - t0, 1),
    )


# ------------------------------------------------------------------- publish
def content_type(path: Path) -> str:
    return {
        ".parquet": "application/vnd.apache.parquet",
        ".json": "application/json",
    }.get(path.suffix, "application/octet-stream")


def local_outputs(out_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for prefix in OUTPUT_PREFIXES:
        for p in sorted((out_dir / prefix).rglob("*")):
            if p.is_file():
                files[p.relative_to(out_dir).as_posix()] = p
    return files


def publish(store: RemoteStore, out_dir: Path, *, workers: int = 8) -> dict[str, Any]:
    """Unggah keluaran build lalu hapus objek basi di prefix keluaran (staging/, marts/).

    Urutan unggah-dulu-baru-hapus: pembaca tidak pernah melihat prefix kosong; paling buruk
    sesaat melihat partisi lama yang sebentar lagi dihapus.
    """
    files = local_outputs(out_dir)
    if not any(k.startswith("marts/fct_harga_harian/") for k in files):
        raise RuntimeError(f"keluaran build tidak lengkap di {out_dir}, publish dibatalkan")

    def up(item: tuple[str, Path]) -> int:
        key, path = item
        store.upload_file(key, str(path), content_type=content_type(path))
        return path.stat().st_size

    with ThreadPoolExecutor(max_workers=workers) as pool:
        uploaded_bytes = sum(pool.map(up, files.items()))
    stale = [
        o["Key"]
        for prefix in OUTPUT_PREFIXES
        for o in store.list_objects(prefix)
        if o["Key"] not in files
    ]
    if stale:
        store.delete_keys(stale)
    result = {"uploaded": len(files), "uploaded_bytes": uploaded_bytes, "deleted": len(stale)}
    log.info("publish %s", result)
    return result


# -------------------------------------------------------------------- report
def profile_outputs(db_path: Path) -> dict[str, Any]:
    """Statistik & temuan data dari hasil build (untuk ringkasan run dan deskripsi PR)."""
    import duckdb

    # Tanpa read_only: dbt-duckdb masih memegang koneksi ke file yang sama di proses ini.
    con = duckdb.connect(str(db_path))

    def rows(sql: str) -> list[dict[str, Any]]:
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def one(sql: str) -> dict[str, Any]:
        return rows(sql)[0]

    out: dict[str, Any] = {
        "staging": one(
            """
            select count(*) as baris, count(harga) as berharga,
                   min(tanggal) as tanggal_awal, max(tanggal) as tanggal_akhir,
                   count(distinct kode_wilayah) as wilayah,
                   count(distinct _source_path) as file_sumber
            from stg_pihps__harga
            """
        ),
        "fakta": one("select count(*) as baris from fct_harga_harian"),
        # Dipakai pihps.freshness: tanggal harga terbaru seri acuan (nasional, tradisional).
        "terbaru_nasional_tradisional": one(
            """
            select max(tanggal) as tanggal
            from fct_harga_harian
            where kode_wilayah = 'nasional' and jenis_pasar_id = 1
            """
        )["tanggal"],
        "revisi": one(
            """
            -- sel yang muncul di > 1 file raw dengan nilai berbeda (revisi BI atau koreksi)
            select count(*) as sel_direvisi from (
                select tanggal, jenis_pasar_id, kode_wilayah, nama_komoditas_norm,
                       level_komoditas
                from stg_pihps__harga_raw
                group by all
                having count(distinct coalesce(harga, -1)) > 1
            )
            """
        ),
        "per_jenis_pasar": rows(
            """
            select jenis_pasar, count(*) as baris, count(harga) as berharga,
                   round(1 - count(harga) / count(*), 4) as rasio_kosong,
                   min(tanggal) filter (where harga is not null) as tanggal_awal,
                   max(tanggal) as tanggal_akhir,
                   count(distinct kode_wilayah) as wilayah
            from stg_pihps__harga group by all order by jenis_pasar
            """
        ),
        "kosong_per_tahun_tradisional_nasional": rows(
            """
            select tahun, count(*) as sel, count(*) - count(harga) as kosong
            from stg_pihps__harga
            where jenis_pasar_id = 1 and kode_wilayah = 'nasional'
            group by all order by tahun
            """
        ),
        "modern_sama_dengan_tradisional": one(
            """
            -- Temuan probe F0: kategori Beras pasar modern = tradisional. Seberapa sering?
            select count(*) as sel_berpasangan,
                   count(*) filter (where m.harga = t.harga) as sel_identik,
                   round(count(*) filter (where m.harga = t.harga) / nullif(count(*), 0), 4)
                       as rasio_identik
            from fct_harga_harian m
            join fct_harga_harian t using (tanggal, kode_wilayah, komoditas_id)
            where m.jenis_pasar_id = 2 and t.jenis_pasar_id = 1
            """
        ),
        "modern_identik_per_komoditas": rows(
            """
            select m.komoditas_id,
                   round(count(*) filter (where m.harga = t.harga) / count(*), 3)
                       as rasio_identik,
                   count(*) as sel
            from fct_harga_harian m
            join fct_harga_harian t using (tanggal, kode_wilayah, komoditas_id)
            where m.jenis_pasar_id = 2 and t.jenis_pasar_id = 1
            group by all order by rasio_identik desc limit 8
            """
        ),
        "di_luar_rentang_wajar": rows(
            """
            select jenis_pasar, komoditas_id, kode_wilayah, tanggal, harga
            from stg_pihps__harga
            where harga is not null and (harga < 1000 or harga > 500000)
            order by harga desc limit 10
            """
        ),
        "lonjakan_per_jenis_pasar": rows(
            """
            with seri as (
                select *,
                    lag(harga) over w as sebelumnya, lag(tanggal) over w as tanggal_sebelumnya
                from fct_harga_harian
                window w as (
                    partition by jenis_pasar_id, kode_wilayah, komoditas_id order by tanggal
                )
            )
            select jenis_pasar_id, count(*) as lonjakan
            from seri
            where tanggal - tanggal_sebelumnya <= 7
              and (harga > 3 * sebelumnya or harga * 3 < sebelumnya)
            group by all order by jenis_pasar_id
            """
        ),
        "lonjakan_contoh": rows(
            """
            with seri as (
                select *,
                    lag(harga) over w as sebelumnya, lag(tanggal) over w as tanggal_sebelumnya
                from fct_harga_harian
                window w as (
                    partition by jenis_pasar_id, kode_wilayah, komoditas_id order by tanggal
                )
            )
            select jenis_pasar_id, kode_wilayah, komoditas_id, tanggal_sebelumnya,
                   sebelumnya, tanggal, harga
            from seri
            where tanggal - tanggal_sebelumnya <= 7
              and (harga > 3 * sebelumnya or harga * 3 < sebelumnya)
            order by greatest(harga / sebelumnya, sebelumnya / harga) desc limit 10
            """
        ),
        "dim_wilayah": rows(
            """
            select level_wilayah, count(*) as versi,
                   count(*) filter (where is_current) as terkini
            from dim_wilayah group by all order by level_wilayah
            """
        ),
    }
    con.close()
    return out


def format_report(
    sync: SyncStats | None,
    build: BuildResult,
    profile: dict[str, Any] | None,
    published: dict[str, Any] | None,
) -> str:
    icon = "✅" if build.success else "❌"
    if build.success and build.warnings:
        icon = "⚠️"
    lines = [f"{icon} PIHPS transform ({'sukses' if build.success else 'gagal'})"]
    if sync:
        lines.append(
            f"Sync raw: {sync.manifests} manifest, {sync.files_wanted} file "
            f"({sync.files_downloaded} baru, {sync.files_cached} cache, "
            f"{len(sync.files_missing)} hilang), {sync.duration_s}s"
        )
    lines.append(f"dbt build {build.duration_s}s: {build.counts}")
    if profile:
        s = profile["staging"]
        lines.append(
            f"Staging: {s['baris']:,} baris ({s['berharga']:,} berharga), "
            f"{s['tanggal_awal']} → {s['tanggal_akhir']}, {s['wilayah']} wilayah; "
            f"fakta {profile['fakta']['baris']:,} baris; "
            f"{profile['revisi']['sel_direvisi']:,} sel direvisi"
        )
    for w in build.warnings[:8]:
        lines.append(f"⚠️ {w['unique_id']}: {w['failures']} baris")
    for e in build.errors[:8]:
        lines.append(f"❌ {e['unique_id']}: {(e.get('message') or '')[:150]}")
    if published:
        lines.append(
            f"Publish R2: {published['uploaded']} file "
            f"({published['uploaded_bytes'] / 1e6:.1f} MB), {published['deleted']} basi dihapus"
        )
    elif build.success:
        lines.append("Publish: dilewati")
    return "\n".join(lines)


def write_step_summary(report: str, profile: dict[str, Any] | None) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a") as fh:
        fh.write(f"## PIHPS transform\n\n```\n{report}\n```\n")
        if profile:
            fh.write("\n<details><summary>Profil data</summary>\n\n```json\n")
            fh.write(json.dumps(profile, indent=2, default=str, ensure_ascii=False))
            fh.write("\n```\n</details>\n")


# ----------------------------------------------------------------------- CLI
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m pihps.transform", description=__doc__.split("\n")[0]
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--raw-dir", type=Path, default=Path("data"), help="berisi raw/pihps/")
        p.add_argument("--out-dir", type=Path, default=Path("data/out"))
        p.add_argument("--db", type=Path, default=Path("data/pihps.duckdb"))

    p_sync = sub.add_parser("sync", help="salin raw dari R2 lewat manifest")
    common(p_sync)
    p_build = sub.add_parser("build", help="dbt build dari raw lokal")
    common(p_build)
    p_build.add_argument("dbt_args", nargs="*", help="argumen tambahan dbt, mis. --select ...")
    p_pub = sub.add_parser("publish", help="unggah keluaran build ke R2")
    common(p_pub)
    p_run = sub.add_parser("run", help="sync + build + (publish)")
    common(p_run)
    p_run.add_argument("--source", choices=["r2", "local"], default="r2")
    p_run.add_argument("--publish", action="store_true", help="unggah hasil ke R2 bila lolos")
    p_run.add_argument(
        "--notify", choices=["failure", "always", "never"], default="failure", help="Telegram"
    )
    p_run.add_argument("--report-out", type=Path, default=Path("transform_report.json"))
    return ap


def _store() -> RemoteStore:
    from pihps.config import R2Config
    from pihps.storage import R2Storage

    return R2Storage(R2Config.from_env())


def _notify(report: str) -> None:
    from pihps.notify import send_telegram

    try:
        sent = send_telegram(to_telegram_html(report))
        log.info("notifikasi Telegram %s", "terkirim" if sent else "TIDAK terkirim")
    except Exception as exc:  # noqa: BLE001 - notifikasi tidak boleh mengubah exit code
        log.error("notifikasi Telegram gagal: %s", exc)


def cmd_run(args: argparse.Namespace) -> int:
    sync = sync_raw(_store(), args.raw_dir) if args.source == "r2" else None
    build = dbt_build(args.raw_dir, args.out_dir, args.db)
    profile = None
    if build.success:
        try:
            profile = profile_outputs(args.db)
        except Exception as exc:  # noqa: BLE001 - profil hanya pelengkap laporan
            log.exception("profil data gagal: %s", exc)
        log.info("profil %s", json.dumps(profile, default=str, ensure_ascii=False))
    published = None
    publish_error = None
    if build.success and args.publish:
        info = {
            "built_at": datetime.now(UTC).isoformat(),
            "git_sha": git_sha(),
            "sync": sync.as_dict() if sync else None,
            "dbt": build.as_dict(),
            "profile": profile,
        }
        (args.out_dir / BUILD_INFO_KEY).write_text(
            json.dumps(info, indent=2, default=str, ensure_ascii=False)
        )
        try:
            published = publish(_store(), args.out_dir)
        except Exception as exc:  # noqa: BLE001
            log.exception("publish gagal")
            publish_error = f"{type(exc).__name__}: {exc}"

    report = format_report(sync, build, profile, published)
    if publish_error:
        report += f"\n❌ publish gagal: {publish_error[:200]}"
    print(report)
    write_step_summary(report, profile)
    args.report_out.write_text(
        json.dumps(
            {
                "sync": sync.as_dict() if sync else None,
                "dbt": build.as_dict(),
                "profile": profile,
                "publish": published,
                "publish_error": publish_error,
            },
            indent=2,
            default=str,
            ensure_ascii=False,
        )
    )
    ok = build.success and not publish_error
    if args.notify == "always" or (args.notify == "failure" and not ok):
        _notify(report)
    return EXIT_OK if ok else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    try:
        if args.cmd == "sync":
            sync_raw(_store(), args.raw_dir)
            return EXIT_OK
        if args.cmd == "build":
            res = dbt_build(args.raw_dir, args.out_dir, args.db, extra_args=args.dbt_args)
            print(format_report(None, res, None, None))
            return EXIT_OK if res.success else EXIT_FAILED
        if args.cmd == "publish":
            publish(_store(), args.out_dir)
            return EXIT_OK
        return cmd_run(args)
    except Exception:
        log.exception("transform berhenti karena error tak terduga")
        return EXIT_ABORTED


if __name__ == "__main__":
    sys.exit(main())
