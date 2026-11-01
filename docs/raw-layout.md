# Layout raw zone (R2)

Ditulis oleh `src/pihps/extract.py`. Raw zone **immutable**: setiap run menulis ke prefix
`run_id=` baru dan tidak pernah menimpa run lain. Isi file = byte respons API **apa adanya**
(tidak diparse/diubah), dikompres gzip (`mtime=0`, jadi deterministik).

```
raw/pihps/
  endpoint=grid_daerah/jenis_pasar=<slug>/ingest_date=YYYY-MM-DD/run_id=<YYYYMMDDTHHMMSS>/
      nasional=all.json.gz
      provinsi=<province_id>.json.gz
      kabkota=<regency_id>.json.gz
  endpoint=ref_price_type/ingest_date=.../run_id=.../nasional=all.json.gz
  endpoint=ref_commodity/ingest_date=.../run_id=.../nasional=all.json.gz
  endpoint=ref_province/ingest_date=.../run_id=.../nasional=all.json.gz
  endpoint=ref_regency/jenis_pasar=<slug>/ingest_date=.../run_id=.../provinsi=<province_id>.json.gz
  _manifests/ingest_date=YYYY-MM-DD/run_id=<id>/_manifest.json
```

- `slug`: `pasar_tradisional` (1), `pasar_modern` (2), `pedagang_besar` (3), `produsen` (4).
- `ingest_date` dan `run_id` memakai waktu **WIB** saat run dimulai — bukan tanggal harga.
  Tanggal harga ada di kolom respons; rentang yang diminta ada di `params` manifest.
- Kab/kota diminta dengan `province_id` + `regency_id`; `province_id` induknya dicatat di
  manifest (`files[].province_id`). Daftar kab/kota diambil dari `GetRefRegency` per jenis
  pasar per provinsi, jadi cakupannya bisa beda antar jenis pasar.
- **Backfill** (rentang > 31 hari) dipecah per bulan kalender. Supaya tidak bentrok di run
  yang sama, nama file diberi akhiran rentang:
  `provinsi=13_20170601-20170630.json.gz`. Run harian (≤ 31 hari) tidak memakai akhiran.
- `ContentType: application/gzip` tanpa `ContentEncoding`, jadi klien S3 tidak
  mendekompresi otomatis; ukuran objek = `gz_bytes` di manifest.

## Manifest

`_manifest.json` (JSON biasa, tidak di-gzip) — sumber kebenaran untuk staging:

| Field | Isi |
|---|---|
| `run_id`, `ingest_date`, `status` | `status` = `success` / `failed` |
| `scraper_version`, `git_sha` | versi paket `pihps` dan commit (`GITHUB_SHA` atau `git rev-parse`) |
| `params` | rentang tanggal, jenis pasar, level, `tipe_laporan` |
| `summary` | `requests_total`, `http_attempts` (termasuk retry), `succeeded`, `failed`, `records_total`, `bytes_total`, `duration_s`, `silent_failures`, `grid_requests`, `grid_failed`, `grid_empty_by_level`, `empty_or_failed_ratio`, `regencies_by_price_type`, `by_endpoint` |
| `files[]` | `path`, `endpoint`, `jenis_pasar`, `level`, `level_id`, `url`, `params`, `http_status`, `fetched_at` (UTC), `bytes` & `sha256` (respons mentah sebelum gzip), `gz_bytes`, `records`, `ok`, `error` |
| `silent_failures[]`, `warnings[]`, `failed_files[]` | detail kegagalan |

`records` = jumlah elemen non-kosong di `data` (respons kosong PIHPS berbentuk `[{}]`).
Staging sebaiknya hanya membaca file dengan `ok: true` dari manifest run yang dipilih,
bukan glob buta atas prefix.

## Kapan run dianggap gagal (exit code 1)

1. Ada request yang gagal setelah retry (HTTP non-200, timeout, respons bukan `{"data": ...}`)
   atau upload R2 gagal. Wilayah lain tetap diambil; kegagalan dicatat di manifest.
2. **Silent failure**: respons `GetGridDataDaerah` nasional pasar tradisional HTTP 200 tetapi
   tanpa record, tanpa kolom tanggal, atau semua harga kosong. Respons tetap disimpan untuk
   audit.
3. **Silent failure rasio**: (request harga gagal + respons HTTP 200 tanpa record di level
   provinsi & kab/kota) / total request harga (`GetGridDataDaerah`) > 10%. Jumlah kosong per
   level dicatat di `summary.grid_empty_by_level`, rasionya di `summary.empty_or_failed_ratio`.
4. Manifest gagal ditulis ke R2.

Peringatan (tidak menggagalkan run): jumlah provinsi dari `GetRefProvince` ≠ 34.
