from datetime import UTC, date, datetime

from pihps.freshness import business_days_between, evaluate, format_report, load_holidays

# Senin 2 Nov 2026, 17.00 WIB
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def info(latest: str | None, built_at: str | None = "2026-11-02T08:30:00+00:00"):
    return {"built_at": built_at, "profile": {"terbaru_nasional_tradisional": latest}}


def test_business_days_skip_weekend():
    # Jumat 30 Okt -> Senin 2 Nov = 1 hari kerja
    assert business_days_between(date(2026, 10, 30), date(2026, 11, 2)) == 1
    assert business_days_between(date(2026, 11, 2), date(2026, 11, 2)) == 0
    assert business_days_between(date(2026, 10, 26), date(2026, 11, 2)) == 5


def test_fresh_after_weekend():
    res = evaluate(info("2026-10-30"), NOW)
    assert res.ok and res.lag_business_days == 1
    assert format_report(res).startswith("✅")


def test_stale_data_beyond_three_business_days():
    # Senin 26 Okt -> Senin 2 Nov = 5 hari kerja
    res = evaluate(info("2026-10-26"), NOW)
    assert not res.ok
    assert "data basi" in res.problems[0]
    assert format_report(res).startswith("⚠️")


def test_threshold_is_inclusive():
    # Rabu 28 Okt -> Senin 2 Nov = 3 hari kerja: masih segar
    assert evaluate(info("2026-10-28"), NOW).ok
    assert not evaluate(info("2026-10-28"), NOW, max_business_days=2).ok


def test_stale_build_detected():
    res = evaluate(info("2026-10-30", built_at="2026-10-31T08:30:00+00:00"), NOW)
    assert not res.ok
    assert any("build basi" in p for p in res.problems)


def test_missing_fields_are_problems():
    res = evaluate({"built_at": None, "profile": None}, NOW)
    assert not res.ok and len(res.problems) == 2


def test_holidays_are_not_business_days():
    # Lebaran 2026: Jumat 20 Mar - Selasa 24 Mar libur/cuti bersama
    hol = load_holidays()
    assert date(2026, 3, 21) in hol and date(2026, 3, 24) in hol
    # Kamis 19 Mar (Nyepi) juga libur; Rabu 18 Mar cuti bersama
    assert business_days_between(date(2026, 3, 17), date(2026, 3, 25), hol) == 1
    assert business_days_between(date(2026, 3, 17), date(2026, 3, 25)) == 6


def test_lebaran_does_not_trigger_stale_alert():
    after_lebaran = datetime(2026, 3, 26, 10, 0, tzinfo=UTC)  # Kamis 26 Mar
    built = "2026-03-26T08:30:00+00:00"
    res = evaluate(info("2026-03-17", built_at=built), after_lebaran, holidays=load_holidays())
    assert res.ok, res.problems
    assert res.lag_business_days == 2
    assert not evaluate(info("2026-03-17", built_at=built), after_lebaran).ok
