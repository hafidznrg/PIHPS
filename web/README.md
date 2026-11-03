# Situs harga pangan (F4)

Situs statis Astro + ECharts untuk masyarakat umum: harga hari ini per wilayah, naik/turun dari
minggu lalu, peta provinsi, tren komoditas sejak 2017, rantai pasok produsen → pasar, dan halaman
**Jelajahi** (SQL di peramban dengan DuckDB-WASM atas Parquet marts). Tidak ada server: semua
data berasal dari **serving layer** (`serving/` di R2) yang dibuat dbt + `pihps.serving`.

```
R2 serving/*.json ──► public/data/serving ──► astro build (halaman statis per wilayah & komoditas)
R2 marts/*.parquet ─► public/data/marts ────► /jelajahi/ (DuckDB-WASM, HTTP range)
```

## Menjalankan lokal

```bash
# dari root repo: data sintetis lewat jalur yang sama dengan produksi (raw -> dbt -> serving)
uv run python -m pihps.serving demo --dest web/public/data
# atau data nyata (butuh env R2_*)
uv run python -m pihps.serving download --dest web/public/data

cd web
npm ci
npm run dev            # http://localhost:4321
npm run check          # astro check (TypeScript strictest)
npm test               # vitest: format, render, kontrak JSON Schema
npm run build && npx playwright test   # e2e HP & desktop (E2E_OFFLINE=1 melewati DuckDB-WASM)
```

Tanpa akses CDN (mis. sandbox), halaman Jelajahi bisa memakai bundle lokal:
`node scripts/copy-duckdb.mjs && PUBLIC_DUCKDB_BUNDLE=local npm run build` (ekstensi Parquet
tetap diunduh dari `extensions.duckdb.org`).

## Struktur

| Path | Isi |
| --- | --- |
| `src/lib/types.ts` | tipe kontrak serving (cermin `src/pihps/serving_schemas/*.schema.json`) |
| `src/lib/render.ts`, `html.ts` | papan harga (baris per komoditas), kalimat ringkasan & sparkline SVG: fungsi murni yang sama dipakai saat build dan di peramban, dengan escaping otomatis |
| `src/lib/charts.ts` | ECharts modular + tema dari CSS variables (terang/gelap), warna tetap per jenis pasar |
| `src/lib/duck.ts` | DuckDB-WASM: bundle jsDelivr (versi = package-lock), view `harga`, `wilayah`, `komoditas`, `pasar`, `tanggal` |
| `src/components/HargaWilayah.astro` | tampilan utama beranda & `/wilayah/<kode>/` |
| `src/pages/` | `/`, `/wilayah/`, `/komoditas/`, `/peta/`, `/jelajahi/`, `/tentang/` |
| `src/data/provinsi-34.geo.json` | 34 provinsi, kode BPS (dibuat `scripts/prep_geo.py`, sumber MIT) |
| `tests/unit/contract.test.ts` | validasi data situs terhadap JSON Schema yang sama dengan pipeline Python |

## Prinsip

- **Gaya buletin pasar**: kertas & tinta, judul serif (Newsreader), teks IBM Plex Sans, angka harga
  IBM Plex Mono (tabular, sejajar). Pemisah berupa garis tipis, bukan kartu/bayangan; tab bergaris
  bawah. Font di-*self-host* lewat `@fontsource` (tanpa CDN pihak ketiga). Mode gelap ikut sistem.
- **Mobile-first & cepat**: HTML statis; papan harga & sparkline tanpa JS; ECharts dimuat
  hanya saat grafik terlihat; DuckDB-WASM hanya setelah pengguna menekan "Mulai".
- **Bahasa awam**: harga per kg, "naik/turun dari minggu lalu", arah selalu ditandai ikon
  ▲▼ dan kata untuk pembaca layar (bukan warna saja); naik = merah karena sudut pandang pembeli.
- **Aksesibel**: semantik HTML, `<select>` native, tab ARIA, tabel cadangan untuk peta, fokus terlihat.
- **Atribusi** ke PIHPS Nasional – Bank Indonesia di setiap halaman.

## Deploy

Workflow [`web`](../.github/workflows/web.yml) berjalan setelah `transform` sukses: unduh data
nyata dari R2 → uji kontrak → build (`SITE_BASE=/PIHPS`) → e2e pada data nyata → GitHub Pages
(hanya dari `main`). Pages harus diaktifkan sekali: **Settings → Pages → Source: GitHub Actions**.
