import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from raw_factory import build_raw, write_run

from pihps.transform import (
    MANIFEST_PREFIX,
    dbt_build,
    format_report,
    profile_outputs,
    publish,
    sync_raw,
    wanted_files,
)


# --------------------------------------------------------------- store tiruan
class DirStore:
    """RemoteStore tiruan di atas direktori lokal (key = path relatif)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.downloads: list[str] = []
        self.uploads: list[str] = []
        self.deleted: list[str] = []

    def list_objects(self, prefix: str) -> list[dict[str, Any]]:
        return [
            {"Key": p.relative_to(self.root).as_posix(), "Size": p.stat().st_size}
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and p.relative_to(self.root).as_posix().startswith(prefix)
        ]

    def download_file(self, key: str, path: str) -> None:
        self.downloads.append(key)
        shutil.copyfile(self.root / key, path)

    def upload_file(self, key: str, path: str, *, content_type: str) -> None:
        self.uploads.append(key)
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)

    def delete_keys(self, keys: list[str]) -> None:
        self.deleted.extend(keys)
        for k in keys:
            (self.root / k).unlink()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Raw tiruan -> dbt build penuh, sekali untuk semua tes di modul ini."""
    root = tmp_path_factory.mktemp("lake")
    build_raw(root)
    res = dbt_build(root, root / "out", root / "pihps.duckdb")
    return root, res


def query(root: Path, sql: str) -> list[tuple]:
    con = duckdb.connect()
    try:
        return con.execute(sql.replace("$OUT", str(root / "out"))).fetchall()
    finally:
        con.close()


STG = "read_parquet('$OUT/staging/stg_pihps__harga/**/*.parquet', hive_partitioning = true)"
FCT = "read_parquet('$OUT/marts/fct_harga_harian/**/*.parquet', hive_partitioning = true)"


# --------------------------------------------------------------------- unit
def test_wanted_files_skips_failed_and_empty_grid():
    manifest = {
        "files": [
            {"path": "a", "endpoint": "GetGridDataDaerah", "ok": True, "records": 31},
            {"path": "b", "endpoint": "GetGridDataDaerah", "ok": True, "records": 0},
            {"path": None, "endpoint": "GetGridDataDaerah", "ok": False, "records": None},
            {"path": "c", "endpoint": "GetRefRegency", "ok": True, "records": 0},
            {"path": "d", "endpoint": "GetRefProvince", "ok": False, "records": 34},
        ]
    }
    assert [f["path"] for f in wanted_files(manifest)] == ["a", "c"]


# ---------------------------------------------------------------- dbt build
def test_dbt_build_succeeds_and_writes_parquet(built):
    root, res = built
    assert res.success, res.errors
    assert not res.errors
    assert res.counts.get("pass", 0) > 30
    out = root / "out"
    assert (out / "staging/stg_pihps__harga/tahun=2026/bulan=10").is_dir()
    assert (out / "marts/fct_harga_harian/tahun=2026").is_dir()
    for dim in ("dim_wilayah", "dim_komoditas", "dim_pasar", "dim_tanggal"):
        assert (out / f"marts/{dim}.parquet").is_file()


def test_staging_dedup_latest_wins(built):
    root, _ = built
    rows = query(
        root,
        f"""select tanggal, harga, harga_raw, _run_id from {STG}
            where kode_wilayah = 'nasional' and jenis_pasar_id = 1 and komoditas_id = 'cat_1'
            order by tanggal""",
    )
    by_date = {r[0]: r for r in rows}
    assert len(rows) == 5  # 26-30 Okt, tanpa duplikat
    # 30 Okt: run lama '-' (NULL), run baru 16,600 -> versi terbaru menang
    assert by_date[date(2026, 10, 30)][1:] == (16600, "16,600", "20261101T150000")
    # 26 Okt hanya ada di run lama
    assert by_date[date(2026, 10, 26)][3] == "20261030T150000"


def test_staging_keeps_null_and_ignores_orphan_files(built):
    root, _ = built
    # pasar modern hanya di run lama -> '-' tetap ada sebagai NULL di staging
    assert query(
        root,
        f"""select harga, harga_raw from {STG} where kode_wilayah = 'nasional'
            and jenis_pasar_id = 2 and komoditas_id = 'cat_1' and tanggal = '2026-10-30'""",
    ) == [(None, "-")]
    # file yatim (tanpa manifest) berisi 99,999 tidak boleh terbaca
    assert query(root, f"select count(*) from {STG} where harga = 99999") == [(0,)]
    # kab/kota kosong ([{}]) tidak menghasilkan baris
    assert query(root, f"select count(*) from {STG} where kode_wilayah = 'kab-34'") == [(0,)]


def test_staging_unique_key_and_mappings(built):
    root, _ = built
    dup = query(
        root,
        f"""select count(*) from (select tanggal, jenis_pasar_id, kode_wilayah, komoditas_id
            from {STG} group by all having count(*) > 1)""",
    )
    assert dup == [(0,)]
    # DKI Jakarta: id PIHPS 13 -> BPS 31; Kota Bandung ikut kode provinsi Jawa Barat (32)
    assert query(
        root,
        f"""select distinct kode_wilayah, kode_bps_provinsi from {STG}
            where kode_wilayah in ('prov-13', 'kab-27') order by 1""",
    ) == [("kab-27", "32"), ("prov-13", "31")]
    assert query(
        root, f"select distinct kode_bps_kabkota from {STG} where kode_wilayah = 'kab-27'"
    ) == [("3273",)]
    # nama ber-spasi berlebih tetap terpetakan
    assert query(
        root, f"select distinct komoditas_id from {STG} where nama_komoditas like 'Cabai Merah K%'"
    ) == [("com_14",)]


def test_marts_dimensions(built):
    root, _ = built
    out = root / "out/marts"
    assert query(root, f"select count(*) from '{out}/dim_komoditas.parquet'") == [(31,)]
    assert query(
        root, f"select jenis_pasar_id, jenis_pasar from '{out}/dim_pasar.parquet' order by 1"
    ) == [(1, "pasar_tradisional"), (2, "pasar_modern"), (3, "pedagang_besar"), (4, "produsen")]
    wil = query(
        root,
        f"""select kode_wilayah, nama, nama_provinsi, kode_bps, valid_from, is_current
            from '{out}/dim_wilayah.parquet' where kode_wilayah in ('kab-27', 'prov-12')
            order by 1""",
    )
    assert wil == [
        ("kab-27", "Kota Bandung", "Jawa Barat", "3273", date(2017, 6, 1), True),
        ("prov-12", "Jawa Barat", "Jawa Barat", "32", date(2017, 6, 1), True),
    ]
    # setiap fakta tergabung ke versi dimensi wilayah
    assert query(root, f"select count(*) from {FCT} where wilayah_sk is null") == [(0,)]
    assert query(root, f"select count(*) from {FCT} where harga is null") == [(0,)]


def test_profile_and_report(built):
    root, res = built
    profile = profile_outputs(root / "pihps.duckdb")
    assert profile["staging"]["tanggal_akhir"] == date(2026, 10, 30)
    assert profile["revisi"]["sel_direvisi"] > 0
    report = format_report(None, res, profile, None)
    assert report.startswith("✅ PIHPS transform (sukses)")
    assert "fakta" in report


# ------------------------------------------------------------ tes kualitas
def _build_with(tmp_path: Path, overrides: dict[tuple[str, str], str]):
    write_run(
        tmp_path,
        "20261101T150000",
        date(2026, 11, 1),
        start=date(2026, 10, 26),
        end=date(2026, 10, 30),
        price_types=[1],
        levels=["nasional"],
        overrides=overrides,
    )
    return dbt_build(tmp_path, tmp_path / "out", tmp_path / "pihps.duckdb")


def test_unparseable_price_fails_build(tmp_path):
    res = _build_with(tmp_path, {("Beras", "27/10/2026"): "16.450,5 kg"})
    assert not res.success
    assert any("assert_harga_raw_terparse" in e["unique_id"] for e in res.errors)


def test_price_outlier_is_warning_only(tmp_path):
    res = _build_with(tmp_path, {("Beras", "28/10/2026"): "1,650,000"})
    assert res.success, res.errors
    warned = {w["unique_id"].split(".")[0] for w in res.warnings}
    assert any("dalam_rentang_stg_pihps__harga_harga" in w for w in warned)
    assert any("assert_lonjakan_harga_harian" in w for w in warned)


# ----------------------------------------------------------- sync & publish
def test_sync_raw_reads_through_manifest_and_is_incremental(tmp_path):
    remote = tmp_path / "remote"
    build_raw(remote)
    store = DirStore(remote)
    local = tmp_path / "local"

    stats = sync_raw(store, local, workers=4)
    manifests = list(remote.glob("raw/pihps/_manifests/*/*/_manifest.json"))
    assert stats.manifests == len(manifests) == 2
    expected = set()
    for m in manifests:
        expected |= {f["path"] for f in wanted_files(json.loads(m.read_text()))}
    synced = {
        p.relative_to(local).as_posix()
        for p in local.rglob("*.json.gz")
        if not p.relative_to(local).as_posix().startswith(MANIFEST_PREFIX)
    }
    assert synced == expected
    assert not any("run_id=20261101T999999" in k for k in synced)  # file yatim
    assert not any("kabkota=34" in k for k in synced)  # respons harga kosong
    assert stats.files_downloaded == len(expected) and not stats.files_missing

    store.downloads.clear()
    again = sync_raw(store, local, workers=4)
    assert store.downloads == [] and again.files_cached == len(expected)


def test_sync_raw_records_missing_files(tmp_path):
    remote = tmp_path / "remote"
    build_raw(remote)
    victim = next(remote.glob("raw/pihps/endpoint=grid_daerah/**/provinsi=13.json.gz"))
    victim.unlink()
    stats = sync_raw(DirStore(remote), tmp_path / "local", workers=2)
    assert stats.files_missing == [victim.relative_to(remote).as_posix()]


def test_publish_uploads_and_removes_stale(tmp_path, built):
    root, _ = built
    remote = tmp_path / "remote"
    stale = remote / "staging/stg_pihps__harga/tahun=2017/bulan=6/data_0.parquet"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"lama")
    keep = remote / "raw/pihps/x.json.gz"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"raw")
    store = DirStore(remote)

    result = publish(store, root / "out", workers=2)
    assert "marts/dim_wilayah.parquet" in store.uploads
    assert store.deleted == ["staging/stg_pihps__harga/tahun=2017/bulan=6/data_0.parquet"]
    assert keep.exists()  # raw tidak pernah disentuh
    assert result["deleted"] == 1


def test_publish_refuses_incomplete_output(tmp_path):
    (tmp_path / "out/marts").mkdir(parents=True)
    with pytest.raises(RuntimeError):
        publish(DirStore(tmp_path / "remote"), tmp_path / "out")
