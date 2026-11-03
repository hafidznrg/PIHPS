# PIHPS Harga Pangan

Pipeline data end-to-end untuk harga pangan strategis Indonesia: pengambilan data harian dari
PIHPS Nasional (Bank Indonesia), penyimpanan di data lake, transformasi dengan dbt + DuckDB,
sampai visualisasi web yang mudah dipahami masyarakat umum.

> Sumber data: **Pusat Informasi Harga Pangan Strategis (PIHPS) Nasional, Bank Indonesia** —
> <https://www.bi.go.id/hargapangan>. Proyek ini tidak berafiliasi dengan Bank Indonesia.

## Arsitektur (rencana)

```
GitHub Actions (cron harian)
  └─ extractor (Python/httpx) ──► R2 raw/      JSON asli, immutable, + manifest
        └─ dbt-duckdb         ──► R2 staging/  Parquet bersih, ter-dedup
                              ──► R2 marts/    model dimensional
                              ──► R2 serving/  agregat kecil untuk web
  Alert Telegram: gagal, silent failure, data basi
```

## Status

- [x] Identifikasi sumber & endpoint — lihat [docs/api-notes.md](docs/api-notes.md)
- [x] Probe akses dari GitHub Actions (lihat temuan di docs/api-notes.md)
- [x] Extractor harian → raw — lihat [docs/raw-layout.md](docs/raw-layout.md)
- [x] Staging & marts (dbt-duckdb) — lihat [transform/README.md](transform/README.md)
- [x] Alerting & freshness
- [x] Backfill historis nasional + provinsi (kab/kota menyusul)
- [x] Web visualisasi — Astro + ECharts + serving layer di <https://hafidznrg.github.io/PIHPS/>, lihat [web/README.md](web/README.md)

## Pengembangan lokal

```bash
uv sync
uv run pytest

# Transformasi (dbt-duckdb): raw lokal di data/raw/pihps -> data/out/{staging,marts,serving}
uv run python -m pihps.transform run --source local --raw-dir data

# Web: data sintetis -> situs lokal (lihat web/README.md)
uv run python -m pihps.serving demo --dest web/public/data && (cd web && npm ci && npm run dev)
uv run python -m pihps.probe   # butuh env R2_* dan TELEGRAM_* untuk cek lengkap

# Extractor: default 7 hari terakhir s.d. hari ini (WIB), 4 jenis pasar, semua level
uv run python -m pihps.extract                      # tulis ke R2 (butuh env R2_*)
uv run python -m pihps.extract --local-dir data/    # tulis ke disk lokal, tanpa R2
uv run python -m pihps.extract --start 2017-06-01 --end 2017-12-31 \
    --price-types 1 --levels nasional,provinsi      # backfill, otomatis dipecah per bulan
```

Exit code 1 bila ada wilayah yang gagal, silent failure (respons nasional pasar tradisional
kosong, atau (gagal + kosong) / request harga > 10%), atau manifest gagal ditulis; 2 untuk
argumen tidak valid. Workflow [`extract`](.github/workflows/extract.yml) berjalan dua kali sehari:
10.23 WIB run ringan nasional + provinsi (Telegram hanya bila gagal) dan 15.23 WIB run penuh
termasuk kab/kota (ringkasan Telegram selalu dikirim). Dua jadwal ini menyerap keterlambatan
cron GitHub yang bisa berjam-jam.

Backfill historis: workflow [`backfill`](.github/workflows/backfill.yml) (manual) menjalankan
matriks `jenis_pasar × tahun` secara berurutan lalu mengirim satu ringkasan ke Telegram.
Rencana jobnya bisa dilihat lokal dengan
`uv run python -m pihps.backfill plan --last 2026-10-31`.
