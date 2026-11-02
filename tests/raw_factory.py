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
