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
- [ ] Staging & marts (dbt)
- [ ] Alerting & freshness
- [ ] Backfill historis
- [ ] Web visualisasi

## Pengembangan lokal

```bash
uv sync
uv run pytest
uv run python -m pihps.probe   # butuh env R2_* dan TELEGRAM_* untuk cek lengkap

# Extractor: default 7 hari terakhir s.d. hari ini (WIB), 4 jenis pasar, semua level
uv run python -m pihps.extract                      # tulis ke R2 (butuh env R2_*)
uv run python -m pihps.extract --local-dir data/    # tulis ke disk lokal, tanpa R2
uv run python -m pihps.extract --start 2017-06-01 --end 2017-12-31 \
    --price-types 1 --levels nasional,provinsi      # backfill, otomatis dipecah per bulan
```

Exit code 1 bila ada wilayah yang gagal, silent failure (respons nasional pasar tradisional
kosong, atau (gagal + kosong) / request harga > 10%), atau manifest gagal ditulis; 2 untuk
argumen tidak valid. Workflow [`extract`](.github/workflows/extract.yml) berjalan setiap hari
pukul 15.00 WIB (08:00 UTC) dan selalu mengirim ringkasan ke Telegram.
