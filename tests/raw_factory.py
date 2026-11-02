"""Bangun raw zone tiruan (layout persis seperti R2) memakai Extractor + server tiruan.

Dipakai oleh tes transformasi dbt. Dua run dengan rentang tumpang-tindih mensimulasikan
run harian yang mengambil ulang 7 hari terakhir dan revisi harga dari BI.
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from pihps.client import PihpsClient
from pihps.extract import Extractor, LocalSink, RunParams, manifest_key

FIXTURES = Path(__file__).parent / "fixtures"
GRID = json.loads((FIXTURES / "grid_daerah_nasional.json").read_text())
PROVINCES = (FIXTURES / "ref_province.json").read_bytes()
COMMODITIES = (FIXTURES / "ref_commodity.json").read_bytes()
PRICE_TYPES = (
    b'{"data":[{"id":1,"name":"Pasar Tradisional"},{"id":2,"name":"Pasar Modern"},'
    b'{"id":3,"name":"Pedagang Besar"},{"id":4,"name":"Produsen"}]}'
)
REGENCIES = {
    (1, "13"): [{"id": 34, "name": "Kota Jakarta Pusat"}],
    (1, "12"): [{"id": 27, "name": "Kota Bandung"}],
}


def grid_payload(start: date, end: date, overrides: dict[tuple[str, str], str]) -> bytes:
    """Fixture grid nasional, dipotong ke [start, end]; `overrides` {(nama, dd/mm/yyyy): v}."""
    rows = []
    for rec in GRID["data"]:
        out: dict[str, Any] = {k: v for k, v in rec.items() if "/" not in k}
        for k, v in rec.items():
            if "/" not in k:
                continue
            d, m, y = (int(x) for x in k.split("/"))
            if start <= date(y, m, d) <= end:
                out[k] = overrides.get((rec["name"], k), v)
        rows.append(out)
    return json.dumps({"data": rows}).encode()


def make_handler(overrides: dict[tuple[str, str], str], empty: set[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        ep = request.url.path.rsplit("/", 1)[-1]
        q = request.url.params
        if ep == "GetRefPriceType":
            return httpx.Response(200, content=PRICE_TYPES)
        if ep == "GetRefCommodityAndCategory":
            return httpx.Response(200, content=COMMODITIES)
        if ep == "GetRefProvince":
            return httpx.Response(200, content=PROVINCES)
        if ep == "GetRefRegency":
            regs = REGENCIES.get((int(q["price_type_id"]), q["ref_prov_id"]), [{}])
            return httpx.Response(200, json={"data": regs})
        if ep == "GetGridDataDaerah":
            if (q["regency_id"] or q["province_id"]) in empty:
                return httpx.Response(200, content=b'{"data":[{}]}')
            start = date.fromisoformat(q["start_date"])
            end = date.fromisoformat(q["end_date"])
            return httpx.Response(200, content=grid_payload(start, end, overrides))
        return httpx.Response(404)

    return handler


def write_run(
    root: Path,
    run_id: str,
    ingest_date: date,
    *,
    start: date,
    end: date,
    price_types: list[int],
    levels: list[str],
    overrides: dict[tuple[str, str], str] | None = None,
    empty: set[str] | None = None,
) -> dict[str, Any]:
    client = PihpsClient(
        min_interval=0,
        max_retries=1,
        transport=httpx.MockTransport(make_handler(overrides or {}, empty or set())),
    )
    sink = LocalSink(root)
    params = RunParams(start, end, price_types, levels)
    manifest = Extractor(client, sink, params, run_id, ingest_date, max_empty_ratio=1.0).run()
    sink.put_json(manifest_key(ingest_date, run_id), manifest)
    return manifest


def build_raw(root: Path) -> None:
    """Run lama (26-30 Okt) dan run baru (28-30 Okt) dengan satu harga direvisi & satu '-'."""
    write_run(
        root,
        "20261030T150000",
        date(2026, 10, 30),
        start=date(2026, 10, 26),
        end=date(2026, 10, 30),
        price_types=[1, 2],
        levels=["nasional", "provinsi", "kabkota"],
        overrides={("Beras", "30/10/2026"): "-"},
        empty={"34"},  # Kota Jakarta Pusat kosong
    )
    write_run(
        root,
        "20261101T150000",
        date(2026, 11, 1),
        start=date(2026, 10, 28),
        end=date(2026, 10, 30),
        price_types=[1],
        levels=["nasional", "provinsi"],
        overrides={("Beras", "30/10/2026"): "16,600"},
    )
    # File yatim: ada di raw tetapi tidak tercatat di manifest mana pun -> harus diabaikan.
    orphan = (
        root / "raw/pihps/endpoint=grid_daerah/jenis_pasar=pasar_tradisional/"
        "ingest_date=2026-11-01/run_id=20261101T999999/nasional=all.json.gz"
    )
    orphan.parent.mkdir(parents=True, exist_ok=True)
    payload = grid_payload(
        date(2026, 10, 26), date(2026, 10, 30), {("Beras", "30/10/2026"): "99,999"}
    )
    orphan.write_bytes(gzip.compress(payload))


# ------------------------------------------------------------- data demo sintetis
# Harga dasar per komoditas (Rp/kg) untuk seri sintetis yang tampak wajar di web lokal/CI.
BASE_PRICE = {
    "Beras Kualitas Bawah I": 12500,
    "Beras Kualitas Bawah II": 12200,
    "Beras Kualitas Medium I": 13800,
    "Beras Kualitas Medium II": 13500,
    "Beras Kualitas Super I": 15200,
    "Beras Kualitas Super II": 14800,
    "Daging Ayam Ras Segar": 36000,
    "Daging Sapi Kualitas 1": 135000,
    "Daging Sapi Kualitas 2": 125000,
    "Telur Ayam Ras Segar": 27000,
    "Bawang Merah Ukuran Sedang": 38000,
    "Bawang Putih Ukuran Sedang": 36000,
    "Cabai Merah Besar": 45000,
    "Cabai Merah Keriting ": 47000,
    "Cabai Rawit Hijau": 50000,
    "Cabai Rawit Merah": 60000,
    "Minyak Goreng Curah": 16500,
    "Minyak Goreng Kemasan Bermerk 1": 20500,
    "Minyak Goreng Kemasan Bermerk 2": 19500,
    "Gula Pasir Kualitas Premium": 18500,
    "Gula Pasir Lokal": 17000,
}
# Faktor rantai pasok per jenis pasar (eceran tradisional = 1).
PRICE_TYPE_FACTOR = {1: 1.0, 2: 1.06, 3: 0.88, 4: 0.72}


def synthetic_price(name: str, day: date, region: str, price_type: int) -> int:
    """Harga sintetis deterministik: tren + musiman + gelombang cabai + variasi wilayah."""
    import math
    import zlib

    seed = zlib.crc32(f"{name}|{region}".encode()) / 2**32
    t = (day - date(2017, 6, 1)).days
    volatile = name.startswith(("Cabai", "Bawang"))
    amp = 0.35 if volatile else 0.04
    season = math.sin(2 * math.pi * (t / 365.25 + seed))
    wave = math.sin(2 * math.pi * t / (47 + 30 * seed)) * (0.15 if volatile else 0.01)
    trend = 1 + 0.035 * t / 365.25
    region_factor = 0.9 + 0.25 * seed
    noise = (zlib.crc32(f"{name}|{region}|{t}".encode()) / 2**32 - 0.5) * 0.02
    value = BASE_PRICE[name] * trend * region_factor * PRICE_TYPE_FACTOR[price_type]
    value *= 1 + amp * season + wave + noise
    return int(round(value / 50) * 50)


def synthetic_grid(start: date, end: date, region: str, price_type: int) -> bytes:
    from datetime import timedelta

    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    days = [d for d in days if d.isoweekday() <= 5]
    rows: list[dict[str, Any]] = []
    categories: dict[str, list[str]] = {}
    for rec in GRID["data"]:
        if rec["level"] == 1:
            cat = rec["name"]
            categories[cat] = []
        else:
            categories[cat].append(rec["name"])
    for n, (cat, members) in enumerate(categories.items(), 1):
        prices = {m: {d: synthetic_price(m, d, region, price_type) for d in days} for m in members}
        cat_row: dict[str, Any] = {"no": str(n), "name": cat, "level": 1}
        for d in days:
            avg = sum(prices[m][d] for m in members) / len(members)
            cat_row[f"{d:%d/%m/%Y}"] = f"{int(round(avg / 50) * 50):,}"
        rows.append(cat_row)
        for m in members:
            row: dict[str, Any] = {"no": len(rows), "name": m, "level": 2}
            for d in days:
                row[f"{d:%d/%m/%Y}"] = f"{prices[m][d]:,}"
            rows.append(row)
    return json.dumps({"data": rows}).encode()


def make_demo_handler(provinces: set[str], *, typo: tuple[str, str, date] | None = None):
    """Server tiruan berdata sintetis. `typo` = (provinsi, nama komoditas, tanggal) diberi
    salah digit x10 untuk memeragakan deteksi outlier."""
    prov_payload = json.loads(PROVINCES)
    prov_payload["data"] = [p for p in prov_payload["data"] if str(p["id"]) in provinces]
    regs = {
        "12": [{"id": 27, "name": "Kota Bandung"}],
        "13": [{"id": 34, "name": "Kota Jakarta Pusat"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        ep = request.url.path.rsplit("/", 1)[-1]
        q = request.url.params
        if ep == "GetRefPriceType":
            return httpx.Response(200, content=PRICE_TYPES)
        if ep == "GetRefCommodityAndCategory":
            return httpx.Response(200, content=COMMODITIES)
        if ep == "GetRefProvince":
            return httpx.Response(200, json=prov_payload)
        if ep == "GetRefRegency":
            return httpx.Response(200, json={"data": regs.get(q["ref_prov_id"], [{}])})
        if ep == "GetGridDataDaerah":
            region = (
                q["regency_id"]
                and f"kab-{q['regency_id']}"
                or (q["province_id"] and f"prov-{q['province_id']}" or "nasional")
            )
            pt = int(q["price_type_id"])
            body = synthetic_grid(
                date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"]), region, pt
            )
            if typo and region == f"prov-{typo[0]}" and pt == 1:
                payload = json.loads(body)
                key = f"{typo[2]:%d/%m/%Y}"
                for rec in payload["data"]:
                    if rec["name"] == typo[1] and key in rec:
                        rec[key] = f"{int(rec[key].replace(',', '')) * 10:,}"
                body = json.dumps(payload).encode()
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    return handler


DEMO_PROVINCES = {"12", "13", "14", "16", "26", "33"}


def build_demo_raw(root: Path, *, start: date, end: date) -> None:
    """Raw demo: backfill nasional+provinsi 4 jenis pasar [start, end] + run harian kab/kota."""
    from datetime import timedelta

    typo_day = end - timedelta(days=40)
    while typo_day.isoweekday() > 5:  # PIHPS hanya terbit di hari kerja
        typo_day -= timedelta(days=1)
    common = dict(provinces=DEMO_PROVINCES, typo=("12", "Beras Kualitas Medium I", typo_day))
    for pt in (1, 2, 3, 4):
        client = PihpsClient(
            min_interval=0,
            max_retries=1,
            transport=httpx.MockTransport(make_demo_handler(**common)),
        )
        run_id = f"{end:%Y%m%d}T0{pt}0000"
        params = RunParams(start, end, [pt], ["nasional", "provinsi"])
        sink = LocalSink(root)
        m = Extractor(client, sink, params, run_id, end, max_empty_ratio=1.0).run()
        sink.put_json(manifest_key(end, run_id), m)
    client = PihpsClient(
        min_interval=0, max_retries=1, transport=httpx.MockTransport(make_demo_handler(**common))
    )
    run_id = f"{end:%Y%m%d}T150000"
    params = RunParams(
        end - timedelta(days=6), end, [1, 2, 3, 4], ["nasional", "provinsi", "kabkota"]
    )
    sink = LocalSink(root)
    m = Extractor(client, sink, params, run_id, end, max_empty_ratio=1.0).run()
    sink.put_json(manifest_key(end, run_id), m)
