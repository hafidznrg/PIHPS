# Transformasi dbt-duckdb (F2)

Raw zone PIHPS (JSON.gz + manifest) → **staging** → **marts**, semuanya Parquet di R2.
Dijalankan oleh `python -m pihps.transform` (lihat docstring modul) dan workflow
[`transform`](../.github/workflows/transform.yml) setelah `extract`/`backfill` selesai.

```bash
uv run python -m pihps.transform run --source local --raw-dir data   # dev: raw di data/raw/pihps
uv run python -m pihps.transform run --publish                         # CI: sync R2 -> build -> publish
uv run python -m pihps.transform build --raw-dir data -- --select stg_pihps__harga+
```

## Alur

1. **sync** — daftar `raw/pihps/_manifests/`, unduh manifest, lalu hanya file `ok: true` yang
   tercatat di manifest (respons harga tanpa record dilewati). Inkremental: raw immutable, jadi
   file yang sudah ada di disk (ukuran = `gz_bytes`) tidak diunduh ulang; workflow menyimpan
   `data/raw` di cache Actions.
2. **build** — `dbt build` penuh setiap run (seed → model → tes). DuckDB membaca raw lokal;
   model `external` menulis Parquet ke `data/out/`. Memori DuckDB dibatasi di
   `profiles.yml` (`memory_limit`, default 8GB, ubah lewat env `PIHPS_DUCKDB_MEMORY_LIMIT`;
   `preserve_insertion_order: false`) agar operator besar menumpah ke disk alih-alih OOM di
   runner 16 GB. Manifest dan JSON raw di-parse **sekali** ke tabel DuckDB
   (`stg_pihps__manifest_files`, `stg_pihps__harga_raw`); semua model & tes membaca tabel itu.
3. **publish** — hanya bila tidak ada tes `error`: unggah `data/out/{staging,marts}/` ke R2
   dengan key yang sama, lalu hapus objek basi di prefix itu. `marts/_build.json` mencatat
   waktu build, git sha, hasil tes, dan profil data.

## Model

| Model | Lokasi R2 | Grain / isi |
| --- | --- | --- |
| `stg_pihps__manifest_files` | (tabel DuckDB) | satu baris per file per manifest |
| `stg_pihps__harga_raw` | (tabel DuckDB) | format panjang sebelum dedup: file raw × komoditas × tanggal |
| `stg_pihps__ref_*` | (view) | semua snapshot referensi (komoditas, provinsi, kab/kota, jenis pasar) |
| `stg_pihps__harga` | `staging/stg_pihps__harga/tahun=…/bulan=…/` | tanggal × jenis_pasar × kode_wilayah × komoditas_id, dedup *latest wins* |
| `fct_harga_harian` | `marts/fct_harga_harian/tahun=…/` | sama, hanya sel berharga, + `wilayah_sk` SCD2 |
| `dim_wilayah` | `marts/dim_wilayah.parquet` | SCD2 nasional/provinsi/kab-kota, `[valid_from, valid_to)` |
| `dim_komoditas` | `marts/dim_komoditas.parquet` | 10 kategori + 21 komoditas, + HET berlaku (seed) |
| `dim_pasar` | `marts/dim_pasar.parquet` | 4 jenis pasar |
| `dim_tanggal` | `marts/dim_tanggal.parquet` | kalender sejak 2017-06-01, `ada_data_pihps`, `is_hari_kerja` (libur & cuti bersama dari seed `hari_libur`) |

Keputusan pemodelan:

- **Membaca raw lewat manifest**: glob file raw di-*inner join* ke `stg_pihps__manifest_files`
  (`ok = true`), sehingga file yatim dari run yang crash sebelum menulis manifest diabaikan.
- **Dedup latest wins**: `row_number()` per kunci, urut `_ingested_at` (= `fetched_at` di
  manifest) menurun. Nilai kosong terbaru (`'-'`) juga menang — staging mencerminkan versi
  terakhir BI. Komoditas yang hilang dari respons terbaru tidak menghapus versi lama.
- **`kode_wilayah`** = kunci natural PIHPS: `nasional`, `prov-<id>`, `kab-<id>` (id PIHPS ≠
  kode BPS). Kode BPS dari seed `wilayah_provinsi_bps` (34) dan `wilayah_kabkota_bps` (171,
  MFD BPS Jan 2018; 23 dipetakan manual, mis. kota pasar Sampit → Kab. Kotawaringin Timur).
- **SCD2 tanpa `dbt snapshot`**: dim_wilayah dihitung ulang dari seluruh snapshot referensi di
  raw (immutable), jadi tidak ada state yang bisa hilang. Versi pertama berlaku sejak
  `data_start` agar fakta backfill 2017 tetap tergabung.
- Komoditas dipetakan dari **nama** (respons harga tidak memuat id) ke `cat_x`/`com_x` per
  level, dengan normalisasi spasi & huruf.

## Serving layer (untuk web)

Model `models/serving/srv_*` (tabel di DuckDB) memuat logika tampilan yang diuji dbt:
`srv_harga_bersih` (fakta tanpa `is_outlier`), `srv_tanggal_acuan`, `srv_harga_terkini`
(harga terbaru + pembanding sebelumnya/7 hari/30 hari/1 tahun dengan *as-of join*, arah, selisih
vs nasional, status aktif), `srv_seri_harian` (90 hari), `srv_seri_bulanan`, `srv_tren_mingguan`,
`srv_wilayah`. `pihps.serving export` menulisnya sebagai JSON berkontrak ke `serving/`:

| File | Isi | Batas |
| --- | --- | --- |
| `meta.json` | jenis pasar, kategori & komoditas (+HET), wilayah ber-data, statistik | 150 KB |
| `wilayah/<kode>.json` | per jenis pasar: terkini, seri harian & bulanan (kolumnar) | 300 KB |
| `peta/<jenis_pasar>.json` | terkini per provinsi per komoditas, kode BPS | 200 KB |
| `tren/<komoditas>.json` | mingguan nasional per jenis pasar, terkini nasional & provinsi | 200 KB |
| `_manifest.json` | daftar file, ukuran, sha256, versi skema | – |

Setiap file divalidasi JSON Schema (`src/pihps/serving_schemas/`) dan batas ukurannya; gagal =
transform gagal dan tidak publish. Situs memvalidasi data yang sama dengan skema yang sama.

`fct_harga_harian.is_outlier` menandai dugaan salah input (harga < Rp500, > Rp1 juta/kg, atau
> 3× / < ⅓ median ±5 hari publikasi di seri yang sama; batas atas absolut menangkap salah input
berkepanjangan seperti Rp12 juta/kg selama sebulan yang ikut mencemari median); data tetap ada di marts, serving memakai sel bersih.

## Tes kualitas data

| Tes | Severity | Arti bila gagal |
| --- | --- | --- |
| unik tanggal × jenis_pasar × kode_wilayah × komoditas_id (staging & fakta) | error | dedup rusak |
| `not_null` kunci, `komoditas_id`, `kode_bps_provinsi`, `wilayah_sk` | error | pemetaan nama/wilayah baru di sumber |
| `assert_harga_raw_terparse` | error | format harga baru dari BI |
| `assert_nama_komoditas_terpetakan_unik` | error | referensi ambigu |
| relationships fakta → semua dimensi | error | dimensi tidak lengkap |
| `accepted_values` jenis pasar, level wilayah; rentang tanggal | error | data di luar domain |
| harga di luar Rp1.000–Rp500.000 | warn | outlier / salah input |
| `assert_lonjakan_harga_harian` (> 3× atau < ⅓ hari publikasi sebelumnya, jeda ≤ 7 hari) | warn | salah input |
| `assert_nasional_tradisional_lengkap` | warn | kategori hilang di hari publikasi |
| `assert_seed_provinsi_cocok_referensi` | warn | arti id provinsi PIHPS berubah |
| `kabkota_terpetakan_ke_bps` | warn | kab/kota PIHPS baru, perlu baris seed |

Tes `warn` tidak menghentikan publish, tetapi jumlahnya masuk ringkasan Telegram & step summary.
