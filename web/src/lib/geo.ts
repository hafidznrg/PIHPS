// Peta provinsi sebagai SVG yang dibangun saat build (Node), bukan di peramban.
// GeoJSON 34 provinsi -> path SVG terproyeksi + disederhanakan. Hasilnya disisipkan langsung
// ke HTML sehingga peta tampil tanpa menunggu JavaScript, ECharts, atau unduhan GeoJSON.
//
// Proyeksi: equirectangular dengan faktor cos(lintang tengah). Indonesia membentang ±6° di
// sekitar khatulistiwa, jadi distorsinya < 1% dan rasio bentuk pulau tetap benar.
import geojson from "../data/provinsi-34.geo.json";

type Ring = [number, number][];
interface Feature {
  properties: { kode_bps: string; name: string };
  geometry: { type: "MultiPolygon"; coordinates: Ring[][] } | { type: "Polygon"; coordinates: Ring[] };
}

export interface ProvinsiPath {
  kode_bps: string;
  nama: string;
  d: string;
  /** Titik jangkar label (pusat poligon terbesar), dalam satuan viewBox. */
  cx: number;
  cy: number;
}

export interface PetaSvg {
  w: number;
  h: number;
  provinsi: ProvinsiPath[];
}

const LEBAR = 1000;
const PAD = 6;
const TOLERANSI = 0.6; // satuan viewBox (±0,03°): di bawah 1 piksel layar pada lebar peta normal
const LUAS_MIN = 0.6; // pulau lebih kecil dari ini (satuan²) tidak terlihat; dibuang

function area(r: Ring): number {
  let a = 0;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j]![0] + r[i]![0]) * (r[j]![1] - r[i]![1]);
  return a / 2;
}

function centroid(r: Ring): [number, number] {
  let x = 0;
  let y = 0;
  let a = 0;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    const f = r[j]![0] * r[i]![1] - r[i]![0] * r[j]![1];
    x += (r[j]![0] + r[i]![0]) * f;
    y += (r[j]![1] + r[i]![1]) * f;
    a += f;
  }
  return a === 0 ? r[0]! : [x / (3 * a), y / (3 * a)];
}

/** Douglas–Peucker (iteratif) pada titik terproyeksi. */
export function sederhanakan(pts: Ring, tol: number): Ring {
  if (pts.length <= 4) return pts;
  const keep = new Uint8Array(pts.length);
  keep[0] = 1;
  keep[pts.length - 1] = 1;
  const stack: [number, number][] = [[0, pts.length - 1]];
  const tol2 = tol * tol;
  while (stack.length) {
    const [s, e] = stack.pop()!;
    const [ax, ay] = pts[s]!;
    const [bx, by] = pts[e]!;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    let maxD = -1;
    let idx = -1;
    for (let i = s + 1; i < e; i++) {
      const [px, py] = pts[i]!;
      let d2: number;
      if (len2 === 0) d2 = (px - ax) ** 2 + (py - ay) ** 2;
      else {
        const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
        d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2;
      }
      if (d2 > maxD) {
        maxD = d2;
        idx = i;
      }
    }
    if (maxD > tol2 && idx > 0) {
      keep[idx] = 1;
      stack.push([s, idx], [idx, e]);
    }
  }
  return pts.filter((_, i) => keep[i]);
}

/** Ring -> path SVG ringkas: koordinat bulat, perintah relatif, titik kembar dibuang. */
export function pathRelatif(r: Ring): string {
  // titik terakhir = titik pertama di GeoJSON; "Z" yang menutupnya
  const pts = r.slice(0, -1).map(([x, y]) => [Math.round(x), Math.round(y)] as const);
  let [px, py] = pts[0]!;
  let out = `M${px} ${py}l`;
  let n = 0;
  for (const [x, y] of pts.slice(1)) {
    const dx = x - px;
    const dy = y - py;
    if (dx === 0 && dy === 0) continue;
    out += `${n ? (dx < 0 ? "" : " ") : ""}${dx}${dy < 0 ? "" : " "}${dy}`;
    px = x;
    py = y;
    n += 1;
  }
  return n < 2 ? "" : `${out}z`;
}

let cache: PetaSvg | null = null;

export function petaSvg(): PetaSvg {
  if (cache) return cache;
  const features = (geojson as unknown as { features: Feature[] }).features;
  const polys = (f: Feature): Ring[][] => (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates);

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const f of features)
    for (const p of polys(f))
      for (const [x, y] of p[0]!) {
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
      }
  const kx = Math.cos((((minY + maxY) / 2) * Math.PI) / 180);
  const k = (LEBAR - 2 * PAD) / ((maxX - minX) * kx);
  const proj = ([lon, lat]: [number, number]): [number, number] => [PAD + (lon - minX) * kx * k, PAD + (maxY - lat) * k];
  const h = Math.ceil(2 * PAD + (maxY - minY) * k);

  const provinsi = features.map((f) => {
    let terbesar: { a: number; c: [number, number] } = { a: -1, c: [0, 0] };
    const parts: string[] = [];
    for (const poly of polys(f)) {
      const outer = poly[0]!.map(proj);
      const a = Math.abs(area(outer));
      if (a > terbesar.a) terbesar = { a, c: centroid(outer) };
      if (a < LUAS_MIN) continue;
      for (const ring of poly) {
        const r = sederhanakan(ring.map(proj), TOLERANSI);
        if (r.length < 4 || Math.abs(area(r)) < LUAS_MIN) continue;
        parts.push(pathRelatif(r));
      }
    }
    return {
      kode_bps: f.properties.kode_bps,
      nama: f.properties.name,
      d: parts.join(""),
      cx: Math.round(terbesar.c[0] * 10) / 10,
      cy: Math.round(terbesar.c[1] * 10) / 10,
    };
  });
  cache = { w: LEBAR, h, provinsi };
  return cache;
}
