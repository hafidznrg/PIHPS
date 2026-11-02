import json
from datetime import date

import pytest
from raw_factory import build_demo_raw

from pihps.serving import (
    SIZE_BUDGET,
    ContractError,
    columnar,
    encode,
    export,
    file_name,
    load_schemas,
    validate,
)
from pihps.transform import dbt_build

END = date(2026, 10, 30)


@pytest.fixture(scope="module")
def serving(tmp_path_factory):
    """Raw demo sintetis (Jan 2025 - Okt 2026, 6 provinsi, 4 jenis pasar) -> dbt -> serving."""
    root = tmp_path_factory.mktemp("demo")
    build_demo_raw(root / "raw", start=date(2025, 1, 1), end=END)
    res = dbt_build(root / "raw", root / "out", root / "pihps.duckdb")
    assert res.success, res.errors
    manifest = export(root / "pihps.duckdb", root / "out", generated_at="2026-10-30T10:00:00+00:00")
    return root / "out/serving", manifest


def load(root, path):
    return json.loads((root / path).read_text())


# ---------------------------------------------------------------- util murni
def test_columnar_aligns_series_on_shared_axis():
    rows = [
        {"tanggal": "2026-10-02", "komoditas_id": "com_1", "harga": 2},
        {"tanggal": "2026-10-01", "komoditas_id": "com_1", "harga": 1},
        {"tanggal": "2026-10-02", "komoditas_id": "com_2", "harga": 5},
    ]
    assert columnar(rows, time_key="tanggal", series_key="komoditas_id") == {
        "tanggal": ["2026-10-01", "2026-10-02"],
        "harga": {"com_1": [1, 2], "com_2": [None, 5]},
    }


@pytest.mark.parametrize("bad", ["", "../meta", "prov 1", "a/b"])
def test_file_name_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        file_name(bad)


# ------------------------------------------------------------------- kontrak
def test_export_writes_every_file_and_manifest(serving):
    root, manifest = serving
    paths = {f["path"] for f in manifest["files"]}
    meta = load(root, "meta.json")
    assert {f"wilayah/{w['kode']}.json" for w in meta["wilayah"]} <= paths
    assert {f"peta/{p['slug']}.json" for p in meta["jenis_pasar"]} <= paths
    assert {f"tren/{k['id']}.json" for k in meta["komoditas"]} <= paths
    assert (root / "_manifest.json").exists()
    for f in manifest["files"]:
        assert f["bytes"] <= SIZE_BUDGET[f["schema"]]


def test_meta_content(serving):
    root, _ = serving
    meta = load(root, "meta.json")
    assert meta["tanggal_acuan"] == "2026-10-30"
    assert meta["sumber"]["nama"] == "PIHPS Nasional – Bank Indonesia"
    assert [p["slug"] for p in meta["jenis_pasar"]] == [
        "pasar_tradisional",
        "pasar_modern",
        "pedagang_besar",
        "produsen",
    ]
    assert len(meta["kategori"]) == 10 and len(meta["komoditas"]) == 31
    beras = next(k for k in meta["kategori"] if k["id"] == "cat_1")
    assert beras["komoditas"] == [f"com_{i}" for i in range(1, 7)]
    assert meta["wilayah"][0]["kode"] == "nasional"
    bandung = next(w for w in meta["wilayah"] if w["kode"] == "kab-27")
    assert bandung["kode_bps"] == "3273" and bandung["nama_provinsi"] == "Jawa Barat"
    assert meta["statistik"]["sel_outlier"] == 1  # salah digit yang disisipkan demo


def test_wilayah_terkini_and_series(serving):
    root, _ = serving
    doc = load(root, "wilayah/prov-12.json")
    assert doc["wilayah"]["kode_bps"] == "32"
    trad = next(p for p in doc["pasar"] if p["jenis_pasar_id"] == 1)
    beras = next(t for t in trad["terkini"] if t["komoditas_id"] == "com_3")
    assert beras["tanggal"] == "2026-10-30" and beras["is_aktif"]
    expected = round(100 * (beras["harga"] - beras["harga_7h"]) / beras["harga_7h"], 2)
    assert beras["perubahan_pct_7h"] == pytest.approx(expected)
    assert beras["arah_7h"] in {"naik", "turun", "tetap"}
    # seri harian: sumbu bersama, panjang semua seri sama, hanya hari kerja, <= 90 hari
    harian = trad["harian"]
    n = len(harian["tanggal"])
    assert 55 <= n <= 66
    assert all(len(v) == n for v in harian["harga"].values())
    assert all(date.fromisoformat(t).isoweekday() <= 5 for t in harian["tanggal"])
    # outlier (salah digit x10, ±40 hari sebelum acuan) tidak masuk seri serving
    seri = [v for v in harian["harga"]["com_3"] if v is not None]
    assert max(seri) < 3 * min(seri)
    assert trad["bulanan"]["bulan"][0] == "2025-01"


def test_peta_and_tren(serving):
    root, _ = serving
    peta = load(root, "peta/pasar_tradisional.json")
    rows = peta["komoditas"]["com_13"]
    # id PIHPS 12,13,14,16,26,33 = Jabar, DKI, Jateng, Jatim, Sulsel, Papua
    assert {r["kode_bps"] for r in rows} == {"32", "31", "33", "35", "73", "94"}
    tren = load(root, "tren/com_13.json")
    assert set(tren["mingguan"]["harga"]) == {"1", "2", "3", "4"}
    assert {r["jenis_pasar_id"] for r in tren["nasional_terkini"]} == {1, 2, 3, 4}
    hargas = [r["harga"] for r in tren["provinsi_terkini"]]
    assert hargas == sorted(hargas) and len(hargas) == 6


def test_validate_rejects_schema_violation_and_oversize(serving):
    root, _ = serving
    schemas = load_schemas()
    meta = load(root, "meta.json")
    meta["tanggal_acuan"] = "30/10/2026"
    big = load(root, "tren/com_1.json")
    big["provinsi_terkini"] = big["provinsi_terkini"] * 2000
    with pytest.raises(ContractError) as exc:
        validate({"meta.json": encode(meta), "tren/com_1.json": encode(big)}, schemas)
    msg = str(exc.value)
    assert "meta.json: tanggal_acuan" in msg
    assert "tren/com_1.json" in msg and "> batas" in msg
