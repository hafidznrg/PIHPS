"""Siapkan GeoJSON 34 provinsi untuk peta web: kode BPS, geometri disederhanakan.

Sumber: ans-4175/peta-indonesia-geojson `indonesia-prov.geojson` (MIT, turunan Peta Dasar
BAKOSURTANAL 1:250.000), cakupan 34 provinsi = sama dengan PIHPS. File sumber memakai kode
Kemendagri untuk Papua (91 Papua, 92 Papua Barat); dinormalkan ke kode BPS yang dipakai
seed `wilayah_provinsi_bps` (94 Papua, 91 Papua Barat).

    curl -sSLO https://raw.githubusercontent.com/ans-4175/peta-indonesia-geojson/master/indonesia-prov.geojson
    python scripts/prep_geo.py indonesia-prov.geojson web/src/data/provinsi-34.geo.json
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

TOLERANCE = 0.01  # derajat (~1 km); cukup untuk peta tingkat provinsi di layar HP
DECIMALS = 3
KEMENDAGRI_TO_BPS = {"91": "94", "92": "91"}
SEED = Path(__file__).resolve().parents[1] / "transform/seeds/wilayah_provinsi_bps.csv"


def _perp(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / (dx * dx + dy * dy) ** 0.5


def rdp(points: list, eps: float) -> list:
    """Ramer-Douglas-Peucker iteratif."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        s, e = stack.pop()
        dmax, idx = 0.0, 0
        for i in range(s + 1, e):
            d = _perp(points[i], points[s], points[e])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            keep[idx] = True
            stack += [(s, idx), (idx, e)]
    return [p for p, k in zip(points, keep, strict=True) if k]


def ring(coords: list) -> list | None:
    out = rdp([[round(x, DECIMALS), round(y, DECIMALS)] for x, y in coords], TOLERANCE)
    dedup = [p for i, p in enumerate(out) if i == 0 or p != out[i - 1]]
    if len(dedup) < 4:  # pulau sangat kecil hilang pada skala ini
        return None
    if dedup[0] != dedup[-1]:
        dedup.append(dedup[0])
    return dedup


def polygons(geom: dict) -> list:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    out = []
    for poly in polys:
        rings = [r for r in (ring(r) for r in poly) if r]
        if rings and rings[0]:
            out.append(rings)
    return out


def main(src: str, dest: str) -> int:
    names = {r["kode_bps"]: r["nama_bps"] for r in csv.DictReader(SEED.open())}
    features = []
    for f in json.loads(Path(src).read_text())["features"]:
        kode = str(f["properties"]["kode"])
        kode = KEMENDAGRI_TO_BPS.get(kode, kode)
        polys = polygons(f["geometry"])
        features.append(
            {
                "type": "Feature",
                "properties": {"kode_bps": kode, "name": names[kode]},
                "geometry": {"type": "MultiPolygon", "coordinates": polys},
            }
        )
    features.sort(key=lambda f: f["properties"]["kode_bps"])
    missing = set(names) - {f["properties"]["kode_bps"] for f in features}
    if missing or len(features) != 34:
        raise SystemExit(f"provinsi tidak lengkap: {len(features)} fitur, hilang {missing}")
    doc = {"type": "FeatureCollection", "features": features}
    Path(dest).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(features)} provinsi -> {dest} ({Path(dest).stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
