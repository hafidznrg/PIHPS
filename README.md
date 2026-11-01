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
- [ ] Probe akses dari GitHub Actions
- [ ] Extractor harian → raw
- [ ] Staging & marts (dbt)
- [ ] Alerting & freshness
- [ ] Backfill historis
- [ ] Web visualisasi

## Pengembangan lokal

```bash
uv sync
uv run pytest
uv run python -m pihps.probe   # butuh env R2_* dan TELEGRAM_* untuk cek lengkap
```
