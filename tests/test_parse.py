import json
from datetime import date
from pathlib import Path

import pytest

from pihps.parse import grid_to_rows, parse_price

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("16,450", 16450), ("149,600", 149600), ("-", None), ("", None), (None, None), (12500, 12500)],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_parse_price_rejects_garbage():
    with pytest.raises(ValueError):
        parse_price("n/a")


def test_grid_to_rows_nasional():
    payload = json.loads((FIXTURES / "grid_daerah_nasional.json").read_text())
    rows = grid_to_rows(payload)

    # 31 baris (10 kategori + 21 komoditas) x 5 hari kerja
    assert len(rows) == 31 * 5
    assert {r.tanggal for r in rows} == {date(2026, 10, d) for d in range(26, 31)}

    beras = [r for r in rows if r.nama_komoditas == "Beras Kualitas Medium I"]
    assert beras[0].level == 2
    assert beras[0].harga == 16700
    # nama dengan spasi berlebih di sumber dinormalisasi
    assert any(r.nama_komoditas == "Cabai Merah Keriting" for r in rows)


def test_grid_to_rows_empty():
    assert grid_to_rows({"data": [{}]}) == []
    assert grid_to_rows({"data": []}) == []
