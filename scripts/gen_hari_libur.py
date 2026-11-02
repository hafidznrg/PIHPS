"""Bangkitkan seed transform/seeds/hari_libur.csv (libur nasional + cuti bersama Indonesia).

Sumber: paket `holidays` (MIT), kategori `public` (libur nasional) dan `government` (cuti
bersama SKB 3 Menteri). Bukan dependency pipeline: jalankan ulang bila SKB tahun baru terbit,
lalu tinjau diff-nya.

    uv run --with holidays python scripts/gen_hari_libur.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import holidays

FIRST_YEAR, LAST_YEAR = 2017, 2027
OUT = Path(__file__).resolve().parents[1] / "transform/seeds/hari_libur.csv"


def main() -> int:
    years = range(FIRST_YEAR, LAST_YEAR + 1)
    public = holidays.country_holidays("ID", years=years, categories=("public",), language="id")
    every = holidays.country_holidays(
        "ID", years=years, categories=("public", "government"), language="id"
    )
    rows = []
    for tanggal in sorted(every):
        jenis = "libur_nasional" if tanggal in public else "cuti_bersama"
        # Satu tanggal bisa memuat dua perayaan; get_list memisahkannya.
        nama = "; ".join(every.get_list(tanggal))
        rows.append([tanggal.isoformat(), nama, jenis])
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tanggal", "nama", "jenis"])
        w.writerows(rows)
    print(
        f"{len(rows)} tanggal ({FIRST_YEAR}-{LAST_YEAR}, holidays {holidays.__version__}) -> {OUT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
