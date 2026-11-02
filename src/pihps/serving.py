"""Serving layer: model dbt `srv_*` -> JSON kecil berkontrak di `serving/` untuk web.

    uv run python -m pihps.serving export --db data/pihps.duckdb --out data/out
    uv run python -m pihps.serving download --dest web/public/data   # R2 -> situs (CI web)
    uv run python -m pihps.serving demo --dest web/public/data       # data sintetis (dev/CI)

Kontrak (versi SCHEMA_VERSION, skema JSON di `src/pihps/serving_schemas/`):

    serving/meta.json                  jenis pasar, kategori & komoditas, daftar wilayah
    serving/wilayah/<kode>.json        per wilayah: harga terkini + pembanding, seri harian
                                       N hari terakhir, seri bulanan sejak awal data
    serving/peta/<jenis_pasar>.json    harga terkini per provinsi (kode BPS untuk peta)
    serving/tren/<komoditas_id>.json   rata-rata mingguan nasional per jenis pasar + provinsi
    serving/_manifest.json             daftar file, ukuran, sha256, versi skema

Seri ditulis kolumnar (satu array tanggal bersama + array harga per komoditas, `null` bila
kosong) supaya kecil untuk HP. Setiap file divalidasi terhadap skemanya dan batas ukuran
(`SIZE_BUDGET`); pelanggaran menggagalkan export sehingga publish tidak terjadi.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("serving")

SCHEMA_VERSION = 1
SCHEMA_DIR = Path(__file__).parent / "serving_schemas"
SERVING_PREFIX = "serving"
SOURCE = {"nama": "PIHPS Nasional – Bank Indonesia", "url": "https://www.bi.go.id/hargapangan"}
# Batas ukuran per file (byte, sebelum kompresi). Sengaja ketat: halaman web memuat file ini
# langsung di HP; gzip/brotli dari hosting mengecilkannya lagi ±5-8x.
SIZE_BUDGET = {
    "meta": 150_000,
    "wilayah": 300_000,
    "peta": 200_000,
    "tren": 200_000,
}
TERKINI_FIELDS = (
    "komoditas_id",
    "tanggal",
    "harga",
    "tanggal_sebelumnya",
    "harga_sebelumnya",
    "harga_7h",
    "harga_30h",
    "harga_1th",
    "perubahan_pct_sebelumnya",
    "perubahan_pct_7h",
    "perubahan_pct_30h",
    "perubahan_pct_1th",
    "arah_7h",
    "selisih_pct_nasional",
    "is_aktif",
)


class ContractError(RuntimeError):
    """File serving melanggar skema atau batas ukuran."""


# ------------------------------------------------------------------ util
def _jsonable(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v != v:  # NaN
        return None
    return v


def _rows(con: Any, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [{c: _jsonable(v) for c, v in zip(cols, r, strict=True)} for r in cur.fetchall()]


def columnar(
    rows: list[dict[str, Any]], *, time_key: str, series_key: str, value_key: str = "harga"
) -> dict[str, Any]:
    """[{t, seri, harga}] -> {time_key: [t...], 'harga': {seri: [harga|None, ...]}}."""
    times = sorted({r[time_key] for r in rows})
    index = {t: i for i, t in enumerate(times)}
    series: dict[str, list[Any]] = {}
    for r in rows:
        arr = series.setdefault(str(r[series_key]), [None] * len(times))
        arr[index[r[time_key]]] = r[value_key]
    return {time_key: times, "harga": dict(sorted(series.items()))}


def _month(d: str) -> str:
    return d[:7]


def file_name(kode: str) -> str:
    """Nama file aman untuk kode wilayah/komoditas (sudah [a-z0-9_-], dijaga tetap begitu)."""
    if not kode or any(not (c.isalnum() or c in "-_") for c in kode):
        raise ValueError(f"kode tidak aman untuk nama file: {kode!r}")
    return f"{kode}.json"


# ---------------------------------------------------------------- builders
def build_meta(con: Any, generated_at: str, tanggal_acuan: str) -> dict[str, Any]:
    pasar = _rows(
        con,
        """select jenis_pasar_id as id, jenis_pasar as slug, nama_jenis_pasar as nama,
                  rantai_pasok
           from dim_pasar order by jenis_pasar_id""",
    )
    komoditas = _rows(
        con,
        """select komoditas_id as id, nama_komoditas as nama, tipe, level_komoditas as level,
                  kategori_id, satuan, urutan, het, het_satuan, het_berlaku_mulai, het_sumber
           from dim_komoditas order by level_komoditas, urutan""",
    )
    for k in komoditas:
        het = {
            "harga": k.pop("het"),
            "satuan": k.pop("het_satuan"),
            "berlaku_mulai": k.pop("het_berlaku_mulai"),
            "sumber": k.pop("het_sumber"),
        }
        k["het"] = het if het["harga"] is not None else None
    kategori = [
        {
            "id": k["id"],
            "nama": k["nama"],
            "urutan": k["urutan"],
            "komoditas": [
                c["id"] for c in komoditas if c["kategori_id"] == k["id"] and c["level"] == 2
            ],
        }
        for k in komoditas
        if k["level"] == 1
    ]
    wilayah = _rows(
        con,
        """select kode_wilayah as kode, nama, level_wilayah as level, kode_provinsi,
                  nama_provinsi, kode_bps, jenis_pasar, jenis_pasar_aktif, tanggal_terakhir,
                  is_aktif
           from srv_wilayah
           order by case level_wilayah when 'nasional' then 0 when 'provinsi' then 1 else 2 end,
                    nama_provinsi, nama""",
    )
    stats = _rows(
        con,
        """select count(*) as sel_harga, min(tanggal) as tanggal_awal,
                  max(tanggal) as tanggal_akhir,
                  count(*) filter (where is_outlier) as sel_outlier
           from fct_harga_harian""",
    )[0]
    stats["wilayah"] = len(wilayah)
    return {
        "schema_version": SCHEMA_VERSION,
        "dibuat_pada": generated_at,
        "tanggal_acuan": tanggal_acuan,
        "sumber": SOURCE,
        "jenis_pasar": pasar,
        "kategori": kategori,
        "komoditas": komoditas,
        "wilayah": wilayah,
        "statistik": stats,
    }


def build_wilayah_files(con: Any, meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = ", ".join(TERKINI_FIELDS)
    terkini = defaultdict(list)
    for r in _rows(
        con,
        f"""select kode_wilayah, jenis_pasar_id, {fields}
            from srv_harga_terkini order by kode_wilayah, jenis_pasar_id, komoditas_id""",
    ):
        terkini[(r.pop("kode_wilayah"), r.pop("jenis_pasar_id"))].append(r)
    harian = defaultdict(list)
    for r in _rows(
        con,
        "select kode_wilayah, jenis_pasar_id, tanggal, komoditas_id, harga from srv_seri_harian",
    ):
        harian[(r["kode_wilayah"], r["jenis_pasar_id"])].append(r)
    bulanan = defaultdict(list)
    for r in _rows(
        con,
        "select kode_wilayah, jenis_pasar_id, bulan, komoditas_id, harga from srv_seri_bulanan",
    ):
        r["bulan"] = _month(r["bulan"])
        bulanan[(r["kode_wilayah"], r["jenis_pasar_id"])].append(r)

    out: dict[str, dict[str, Any]] = {}
    for w in meta["wilayah"]:
        pasar = []
        for jp in w["jenis_pasar"]:
            key = (w["kode"], jp)
            pasar.append(
                {
                    "jenis_pasar_id": jp,
                    "terkini": terkini.get(key, []),
                    "harian": columnar(
                        harian.get(key, []), time_key="tanggal", series_key="komoditas_id"
                    ),
                    "bulanan": columnar(
                        bulanan.get(key, []), time_key="bulan", series_key="komoditas_id"
                    ),
                }
            )
        out[f"wilayah/{file_name(w['kode'])}"] = {
            "schema_version": SCHEMA_VERSION,
            "tanggal_acuan": meta["tanggal_acuan"],
            "wilayah": {
                k: w[k]
                for k in ("kode", "nama", "level", "kode_provinsi", "nama_provinsi", "kode_bps")
            },
            "pasar": pasar,
        }
    return out


def build_peta_files(con: Any, meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = _rows(
        con,
        """select t.jenis_pasar_id, t.komoditas_id, t.kode_wilayah, w.kode_bps, w.nama,
                  t.tanggal, t.harga, t.perubahan_pct_7h, t.selisih_pct_nasional, t.is_aktif
           from srv_harga_terkini t
           join srv_wilayah w using (kode_wilayah)
           where w.level_wilayah = 'provinsi'
           order by t.jenis_pasar_id, t.komoditas_id, w.nama""",
    )
    grouped: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        grouped[r.pop("jenis_pasar_id")][r.pop("komoditas_id")].append(r)
    out = {}
    for p in meta["jenis_pasar"]:
        out[f"peta/{file_name(p['slug'])}"] = {
            "schema_version": SCHEMA_VERSION,
            "tanggal_acuan": meta["tanggal_acuan"],
            "jenis_pasar_id": p["id"],
            "komoditas": dict(grouped.get(p["id"], {})),
        }
    return out


def build_tren_files(con: Any, meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mingguan = defaultdict(list)
    for r in _rows(
        con, "select komoditas_id, jenis_pasar_id, minggu, harga from srv_tren_mingguan"
    ):
        mingguan[r["komoditas_id"]].append(r)
    nasional = defaultdict(list)
    provinsi = defaultdict(list)
    fields = ", ".join(f"t.{f}" for f in TERKINI_FIELDS)
    for r in _rows(
        con,
        f"""select t.kode_wilayah, t.jenis_pasar_id, w.nama, w.kode_bps, w.level_wilayah,
                   {fields}
            from srv_harga_terkini t join srv_wilayah w using (kode_wilayah)
            where w.level_wilayah in ('nasional', 'provinsi')
            order by t.komoditas_id, t.jenis_pasar_id, t.harga""",
    ):
        level = r.pop("level_wilayah")
        if level == "nasional":
            for k in ("kode_wilayah", "nama", "kode_bps"):
                r.pop(k)
            nasional[r["komoditas_id"]].append(r)
        elif r["jenis_pasar_id"] == 1 and r["is_aktif"]:
            provinsi[r["komoditas_id"]].append(
                {
                    k: r[k]
                    for k in (
                        "kode_wilayah",
                        "nama",
                        "kode_bps",
                        "tanggal",
                        "harga",
                        "perubahan_pct_7h",
                        "selisih_pct_nasional",
                    )
                }
            )
    out = {}
    for k in meta["komoditas"]:
        kid = k["id"]
        out[f"tren/{file_name(kid)}"] = {
            "schema_version": SCHEMA_VERSION,
            "tanggal_acuan": meta["tanggal_acuan"],
            "komoditas_id": kid,
            "mingguan": columnar(
                mingguan.get(kid, []), time_key="minggu", series_key="jenis_pasar_id"
            ),
            "nasional_terkini": nasional.get(kid, []),
            "provinsi_terkini": provinsi.get(kid, []),
        }
    return out


# -------------------------------------------------------------- validation
def _schema_kind(path: str) -> str:
    return "meta" if path == "meta.json" else path.split("/", 1)[0]


def load_schemas() -> dict[str, Any]:
    return {
        p.name.removesuffix(".schema.json"): json.loads(p.read_text())
        for p in SCHEMA_DIR.glob("*.schema.json")
    }


def validate(files: dict[str, bytes], schemas: dict[str, Any] | None = None) -> None:
    """Validasi skema & batas ukuran semua file; kumpulkan semua pelanggaran sekaligus."""
    from jsonschema import Draft202012Validator

    schemas = schemas or load_schemas()
    validators = {k: Draft202012Validator(v) for k, v in schemas.items()}
    problems: list[str] = []
    for path, body in files.items():
        kind = _schema_kind(path)
        if len(body) > SIZE_BUDGET[kind]:
            problems.append(f"{path}: {len(body):,} B > batas {SIZE_BUDGET[kind]:,} B")
        doc = json.loads(body)
        for err in sorted(validators[kind].iter_errors(doc), key=lambda e: list(e.path))[:3]:
            loc = "/".join(str(p) for p in err.absolute_path)
            problems.append(f"{path}: {loc or '(root)'}: {err.message[:200]}")
    if problems:
        raise ContractError(
            f"{len(problems)} pelanggaran kontrak serving:\n" + "\n".join(problems[:30])
        )


# ------------------------------------------------------------------ export
def encode(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()


def export(db_path: Path, out_dir: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    """Tulis seluruh serving/ dari DuckDB hasil dbt build. Kembalikan isi _manifest.json."""
    import duckdb

    generated_at = generated_at or datetime.now(UTC).isoformat(timespec="seconds")
    # Tanpa read_only: dbt-duckdb di proses yang sama mungkin masih memegang koneksi.
    con = duckdb.connect(str(db_path))
    try:
        acuan = con.execute("select tanggal_acuan from srv_tanggal_acuan").fetchone()
        if not acuan or acuan[0] is None:
            raise ContractError("srv_tanggal_acuan kosong: belum ada harga nasional tradisional")
        tanggal_acuan = acuan[0].isoformat()
        meta = build_meta(con, generated_at, tanggal_acuan)
        docs: dict[str, dict[str, Any]] = {"meta.json": meta}
        docs |= build_wilayah_files(con, meta)
        docs |= build_peta_files(con, meta)
        docs |= build_tren_files(con, meta)
    finally:
        con.close()

    files = {path: encode(doc) for path, doc in docs.items()}
    validate(files)

    root = out_dir / SERVING_PREFIX
    shutil.rmtree(root, ignore_errors=True)
    for path, body in files.items():
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dibuat_pada": generated_at,
        "tanggal_acuan": tanggal_acuan,
        "files": [
            {
                "path": path,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "schema": _schema_kind(path),
            }
            for path, body in sorted(files.items())
        ],
    }
    (root / "_manifest.json").write_bytes(encode(manifest))
    total = sum(f["bytes"] for f in manifest["files"])
    largest = max(manifest["files"], key=lambda f: f["bytes"])
    log.info(
        "serving: %d file, %.1f KB total, terbesar %s (%.1f KB), tanggal acuan %s",
        len(files),
        total / 1e3,
        largest["path"],
        largest["bytes"] / 1e3,
        tanggal_acuan,
    )
    return manifest


# ---------------------------------------------------------------------- CLI
def download(dest: Path, *, include_marts: bool = True) -> None:
    """Salin serving/ (dan marts/ untuk halaman Jelajahi) dari R2 ke direktori situs."""
    from pihps.config import R2Config
    from pihps.storage import R2Storage

    store = R2Storage(R2Config.from_env())
    prefixes = [f"{SERVING_PREFIX}/"] + (["marts/"] if include_marts else [])
    n = 0
    for prefix in prefixes:
        for obj in store.list_objects(prefix):
            path = dest / obj["Key"]
            path.parent.mkdir(parents=True, exist_ok=True)
            store.download_file(obj["Key"], str(path))
            n += 1
    if not (dest / SERVING_PREFIX / "meta.json").exists():
        raise RuntimeError("serving/meta.json tidak ada di R2; jalankan workflow transform dulu")
    log.info("unduh %d file ke %s", n, dest)


def demo(dest: Path, *, start: date, end: date, work: Path) -> None:
    """Bangun data situs dari raw sintetis (tanpa jaringan): raw demo -> dbt -> serving."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from raw_factory import build_demo_raw  # type: ignore[import-not-found]

    from pihps.transform import dbt_build

    shutil.rmtree(work, ignore_errors=True)
    build_demo_raw(work / "raw", start=start, end=end)
    res = dbt_build(work / "raw", work / "out", work / "pihps.duckdb")
    if not res.success:
        raise RuntimeError(f"dbt build demo gagal: {res.errors}")
    export(work / "pihps.duckdb", work / "out")
    for prefix in (SERVING_PREFIX, "marts"):
        shutil.rmtree(dest / prefix, ignore_errors=True)
        shutil.copytree(work / "out" / prefix, dest / prefix)
    log.info("data demo %s → %s ditulis ke %s", start, end, dest)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m pihps.serving", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_exp = sub.add_parser("export", help="DuckDB hasil dbt -> <out>/serving/")
    p_exp.add_argument("--db", type=Path, default=Path("data/pihps.duckdb"))
    p_exp.add_argument("--out", type=Path, default=Path("data/out"))
    p_dl = sub.add_parser("download", help="R2 serving/ + marts/ -> direktori situs")
    p_dl.add_argument("--dest", type=Path, default=Path("web/public/data"))
    p_dl.add_argument("--no-marts", action="store_true")
    p_demo = sub.add_parser("demo", help="data situs sintetis tanpa jaringan")
    p_demo.add_argument("--dest", type=Path, default=Path("web/public/data"))
    p_demo.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p_demo.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 30))
    p_demo.add_argument("--work", type=Path, default=Path("data/demo"))
    args = ap.parse_args(argv)
    try:
        if args.cmd == "export":
            export(args.db, args.out)
        elif args.cmd == "download":
            download(args.dest, include_marts=not args.no_marts)
        else:
            demo(args.dest, start=args.start, end=args.end, work=args.work)
    except ContractError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
