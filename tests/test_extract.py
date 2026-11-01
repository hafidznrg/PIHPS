import gzip
import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from pihps.client import PihpsClient, PihpsError
from pihps.extract import (
    Extractor,
    LocalSink,
    RunParams,
    check_silent_failure,
    manifest_key,
    object_key,
    resolve_range,
    split_range,
)

FIXTURES = Path(__file__).parent / "fixtures"
GRID = (FIXTURES / "grid_daerah_nasional.json").read_bytes()
PROVINCES = (FIXTURES / "ref_province.json").read_bytes()
COMMODITIES = (FIXTURES / "ref_commodity.json").read_bytes()
RUN_ID = "20261101T180000"
INGEST = date(2026, 11, 1)


# ----------------------------------------------------------------- util murni
def test_split_range_short_is_single_chunk():
    assert split_range(date(2026, 10, 26), date(2026, 11, 1)) == [
        (date(2026, 10, 26), date(2026, 11, 1))
    ]


def test_split_range_long_is_monthly():
    chunks = split_range(date(2024, 1, 15), date(2024, 3, 10))
    assert chunks == [
        (date(2024, 1, 15), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 10)),
    ]


def test_split_range_full_year_covers_every_day():
    chunks = split_range(date(2017, 6, 1), date(2018, 5, 31))
    assert len(chunks) == 12
    assert sum((e - s).days + 1 for s, e in chunks) == 365


def test_split_range_rejects_inverted():
    with pytest.raises(ValueError):
        split_range(date(2026, 1, 2), date(2026, 1, 1))


def test_resolve_range_default_is_last_7_days():
    assert resolve_range(None, None, 7, date(2026, 11, 1)) == (
        date(2026, 10, 26),
        date(2026, 11, 1),
    )


def test_object_key_layout():
    key = object_key(
        endpoint="grid_daerah",
        ingest_date=INGEST,
        run_id=RUN_ID,
        level="provinsi",
        level_id=13,
        jenis_pasar="pasar_tradisional",
    )
    assert key == (
        "raw/pihps/endpoint=grid_daerah/jenis_pasar=pasar_tradisional/"
        "ingest_date=2026-11-01/run_id=20261101T180000/provinsi=13.json.gz"
    )
    chunked = object_key(
        endpoint="grid_daerah",
        ingest_date=INGEST,
        run_id=RUN_ID,
        level="nasional",
        level_id="all",
        jenis_pasar="produsen",
        chunk=(date(2017, 6, 1), date(2017, 6, 30)),
    )
    assert chunked.endswith("/nasional=all_20170601-20170630.json.gz")


def test_check_silent_failure():
    assert check_silent_failure(json.loads(GRID)) is None
    assert check_silent_failure({"data": [{}]}) == "respons tanpa record"
    assert check_silent_failure({"data": []}) == "respons tanpa record"
    assert "kolom tanggal" in check_silent_failure({"data": [{"name": "Beras", "level": 1}]})
    all_null = {"data": [{"name": "Beras", "level": 1, "26/10/2026": "-", "27/10/2026": ""}]}
    assert "kosong" in check_silent_failure(all_null)


# ------------------------------------------------------------ fake server
REGENCIES = {
    # (price_type_id, prov_id) -> regencies; cakupan beda per jenis pasar
    (1, "13"): [{"id": 34, "name": "Kota Jakarta Pusat"}],
    (1, "12"): [{"id": 60, "name": "Kota Bandung"}, {"id": 61, "name": "Kota Bogor"}],
    (2, "12"): [{"id": 60, "name": "Kota Bandung"}],
}


def make_server(
    *,
    fail: set[tuple[str, str]] | None = None,
    empty_national: bool = False,
):
    """`fail`: set (endpoint, province_id|regency_id) yang dibalas HTTP 404."""
    fail = fail or set()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        ep = request.url.path.rsplit("/", 1)[-1]
        q = request.url.params
        if ep == "GetRefPriceType":
            return httpx.Response(200, content=b'{"data":[{"id":1,"name":"Pasar Tradisional"}]}')
        if ep == "GetRefCommodityAndCategory":
            return httpx.Response(200, content=COMMODITIES)
        if ep == "GetRefProvince":
            return httpx.Response(200, content=PROVINCES)
        if ep == "GetRefRegency":
            regs = REGENCIES.get((int(q["price_type_id"]), q["ref_prov_id"]), [{}])
            return httpx.Response(200, json={"data": regs})
        if ep == "GetGridDataDaerah":
            if (ep, q["regency_id"] or q["province_id"]) in fail:
                return httpx.Response(404, content=b"not found")
            national = not q["province_id"]
            if national and empty_national and q["price_type_id"] == "1":
                return httpx.Response(200, content=b'{"data":[{}]}')
            return httpx.Response(200, content=GRID)
        return httpx.Response(404)

    return handler, calls


def run_extractor(tmp_path, handler, **params):
    defaults = dict(
        start=date(2026, 10, 26),
        end=date(2026, 11, 1),
        price_types=[1, 2],
        levels=["nasional", "provinsi", "kabkota"],
    )
    defaults.update(params)
    client = PihpsClient(min_interval=0, max_retries=1, transport=httpx.MockTransport(handler))
    ext = Extractor(client, LocalSink(tmp_path), RunParams(**defaults), RUN_ID, INGEST)
    return ext.run()


def test_full_run_writes_raw_bytes_and_manifest(tmp_path):
    handler, calls = make_server()
    m = run_extractor(tmp_path, handler)

    assert m["status"] == "success"
    assert m["run_id"] == RUN_ID
    assert m["params"]["start_date"] == "2026-10-26"
    s = m["summary"]
    # refs: price_type + commodity + province + 2 jenis pasar x 34 provinsi regency
    # grid: 2 x (1 nasional + 34 provinsi) + kab/kota (3 untuk pt1, 1 untuk pt2)
    assert s["requests_total"] == 3 + 2 * 34 + 2 * 35 + 3 + 1
    assert s["failed"] == 0
    assert s["requests_total"] == len(calls)

    # Respons tersimpan byte-per-byte apa adanya
    nat = (
        tmp_path / "raw/pihps/endpoint=grid_daerah/jenis_pasar=pasar_tradisional/"
        "ingest_date=2026-11-01/run_id=20261101T180000/nasional=all.json.gz"
    )
    assert gzip.decompress(nat.read_bytes()) == GRID
    entry = next(f for f in m["files"] if f["path"] == str(nat.relative_to(tmp_path)))
    assert entry["sha256"] == hashlib.sha256(GRID).hexdigest()
    assert entry["bytes"] == len(GRID)
    assert entry["records"] == 31
    assert entry["http_status"] == 200
    assert entry["params"]["province_id"] == ""
    assert entry["url"].startswith("https://www.bi.go.id/hargapangan/WebSite/TabelHarga/")
    assert entry["fetched_at"]

    # Satu request per wilayah: tidak pernah ada ID dipisah koma
    for req in calls:
        for k in ("province_id", "regency_id"):
            assert "," not in req.url.params.get(k, "")

    # Kab/kota sesuai cakupan per jenis pasar
    kab = {(f["jenis_pasar"], f["level_id"]) for f in m["files"] if f["level"] == "kabkota"}
    assert kab == {
        ("pasar_tradisional", 34),
        ("pasar_tradisional", 60),
        ("pasar_tradisional", 61),
        ("pasar_modern", 60),
    }
    bandung = next(
        r
        for r in calls
        if r.url.params.get("regency_id") == "60" and r.url.params["price_type_id"] == "1"
    )
    assert bandung.url.params["province_id"] == "12"

    # Snapshot referensi
    for p in [
        "raw/pihps/endpoint=ref_province/ingest_date=2026-11-01/run_id=20261101T180000/"
        "nasional=all.json.gz",
        "raw/pihps/endpoint=ref_commodity/ingest_date=2026-11-01/run_id=20261101T180000/"
        "nasional=all.json.gz",
        "raw/pihps/endpoint=ref_regency/jenis_pasar=pasar_modern/ingest_date=2026-11-01/"
        "run_id=20261101T180000/provinsi=12.json.gz",
    ]:
        assert (tmp_path / p).exists(), p


def test_failure_in_one_region_does_not_stop_run(tmp_path):
    handler, calls = make_server(fail={("GetGridDataDaerah", "13")})
    m = run_extractor(tmp_path, handler, price_types=[1], levels=["nasional", "provinsi"])

    assert m["status"] == "failed"
    assert m["summary"]["failed"] == 1
    failed = m["failed_files"][0]
    assert (failed["level"], failed["level_id"]) == ("provinsi", 13)
    bad = next(f for f in m["files"] if not f["ok"])
    assert bad["http_status"] == 404
    assert bad["url"] and "province_id=13" in bad["url"]
    # provinsi setelah DKI tetap diambil
    assert m["summary"]["succeeded"] == m["summary"]["requests_total"] - 1
    assert m["summary"]["requests_total"] == 3 + 1 + 34


def test_silent_failure_marks_run_failed(tmp_path):
    handler, _ = make_server(empty_national=True)
    m = run_extractor(tmp_path, handler, price_types=[1, 2], levels=["nasional"])

    assert m["summary"]["failed"] == 0  # semua HTTP 200...
    assert m["status"] == "failed"  # ...tapi tetap gagal
    assert m["silent_failures"][0]["reason"] == "respons tanpa record"
    # respons kosong tetap disimpan apa adanya untuk audit
    nat = next(
        f
        for f in m["files"]
        if f["level"] == "nasional" and f["jenis_pasar"] == "pasar_tradisional"
    )
    assert nat["ok"] and nat["records"] == 0


def test_backfill_range_split_per_month(tmp_path):
    handler, calls = make_server()
    m = run_extractor(
        tmp_path,
        handler,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        price_types=[1],
        levels=["nasional"],
    )
    grids = [r for r in calls if r.url.path.endswith("GetGridDataDaerah")]
    assert [(r.url.params["start_date"], r.url.params["end_date"]) for r in grids] == [
        ("2024-01-01", "2024-01-31"),
        ("2024-02-01", "2024-02-29"),
        ("2024-03-01", "2024-03-31"),
    ]
    paths = sorted(f["path"] for f in m["files"] if f["endpoint"] == "GetGridDataDaerah")
    assert paths[0].endswith("nasional=all_20240101-20240131.json.gz")
    assert len(set(paths)) == 3


def test_manifest_key():
    assert manifest_key(INGEST, RUN_ID) == (
        "raw/pihps/_manifests/ingest_date=2026-11-01/run_id=20261101T180000/_manifest.json"
    )


def test_client_retries_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("pihps.client.time.sleep", lambda s: None)
    responses = iter([httpx.Response(503), httpx.Response(200, content=GRID)])
    client = PihpsClient(min_interval=0, transport=httpx.MockTransport(lambda r: next(responses)))
    raw = client.fetch("GetGridDataDaerah", {"price_type_id": 1})
    assert raw.body == GRID
    assert client.n_requests == 2


def test_client_does_not_retry_4xx(monkeypatch):
    monkeypatch.setattr("pihps.client.time.sleep", lambda s: None)
    client = PihpsClient(
        min_interval=0, transport=httpx.MockTransport(lambda r: httpx.Response(302))
    )
    with pytest.raises(PihpsError) as ei:
        client.fetch("GetRefProvince")
    assert ei.value.status_code == 302
    assert client.n_requests == 1
