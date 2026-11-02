import json
from datetime import date

import pytest

from pihps.backfill import main, plan_jobs, summarize


def test_plan_jobs_per_price_type_and_year():
    jobs = plan_jobs(date(2017, 6, 1), date(2026, 10, 31), [1, 2, 3, 4])
    assert len(jobs) == 4 * 10
    # tradisional dulu, tahun terbaru dulu
    assert jobs[0] == {
        "name": "pasar_tradisional-2026",
        "price_type": 1,
        "jenis_pasar": "pasar_tradisional",
        "year": 2026,
        "start": "2026-01-01",
        "end": "2026-10-31",
    }
    first_2017 = jobs[9]
    assert (first_2017["year"], first_2017["start"], first_2017["end"]) == (
        2017,
        "2017-06-01",
        "2017-12-31",
    )
    assert jobs[10]["jenis_pasar"] == "pasar_modern"
    # tidak ada hari yang terlewat atau ganda per jenis pasar
    days = sum(
        (date.fromisoformat(j["end"]) - date.fromisoformat(j["start"])).days + 1
        for j in jobs
        if j["price_type"] == 1
    )
    assert days == (date(2026, 10, 31) - date(2017, 6, 1)).days + 1


def test_plan_jobs_single_partial_year():
    jobs = plan_jobs(date(2024, 3, 1), date(2024, 4, 30), [2])
    assert [(j["start"], j["end"]) for j in jobs] == [("2024-03-01", "2024-04-30")]


def test_plan_jobs_rejects_inverted():
    with pytest.raises(ValueError):
        plan_jobs(date(2025, 1, 2), date(2025, 1, 1), [1])


def _manifest(pt, start, end, status="success", failed=0, empty=0, sf=None, aborted=False):
    return {
        "status": status,
        "params": {
            "start_date": start,
            "end_date": end,
            "price_types": {str(pt): "x"},  # kunci jadi string setelah JSON
        },
        "summary": {
            "requests_total": 423,
            "failed": failed,
            "records_total": 1000,
            "bytes_total": 2_000_000,
            "duration_s": 700.0,
            "aborted": aborted,
            "grid_empty_by_level": {"nasional": 0, "provinsi": empty, "kabkota": 0},
        },
        "silent_failures": sf or [],
    }


def test_summarize_all_success():
    jobs = plan_jobs(date(2025, 1, 1), date(2026, 3, 31), [1])
    manifests = [_manifest(1, j["start"], j["end"], empty=2) for j in jobs]
    report, ok, totals = summarize(jobs, manifests)
    assert ok
    assert totals["success"] == 2 and totals["requests"] == 846 and totals["empty"] == 4
    assert report.startswith("✅ PIHPS backfill (2/2 job sukses)")
    # urutan job tahun terbaru dulu, tetapi rentang dilaporkan dari tanggal terkecil
    assert "Rentang 2025-01-01 … 2026-03-31" in report


def test_summarize_reports_failed_and_missing():
    jobs = plan_jobs(date(2024, 1, 1), date(2026, 3, 31), [1])  # 2026, 2025, 2024
    manifests = [
        _manifest(1, jobs[0]["start"], jobs[0]["end"]),
        _manifest(
            1,
            jobs[1]["start"],
            jobs[1]["end"],
            status="failed",
            failed=3,
            sf=[{"reason": "rasio 60%"}],
        ),
    ]
    report, ok, totals = summarize(jobs, manifests)
    assert not ok
    assert (totals["success"], totals["failed"], totals["missing"]) == (1, 1, 1)
    assert "pasar_tradisional-2025: rasio 60%; 3 request gagal" in report
    assert "pasar_tradisional-2024: tidak ada manifest" in report


def test_cli_plan_and_summary(tmp_path, capsys):
    assert (
        main(["plan", "--first", "2025-11-01", "--last", "2026-01-31", "--price-types", "1"]) == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert [j["name"] for j in plan["include"]] == [
        "pasar_tradisional-2026",
        "pasar_tradisional-2025",
    ]

    (tmp_path / "plan.json").write_text(json.dumps(plan))
    mdir = tmp_path / "m" / "manifest-1-2026"
    mdir.mkdir(parents=True)
    j = plan["include"][0]
    (mdir / "extract_manifest.json").write_text(json.dumps(_manifest(1, j["start"], j["end"])))
    rc = main(
        ["summary", "--plan", str(tmp_path / "plan.json"), "--manifests", str(tmp_path / "m")]
    )
    assert rc == 1  # job 2025 tidak punya manifest
    assert "1/2 job sukses" in capsys.readouterr().out
