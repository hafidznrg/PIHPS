# Catatan API PIHPS Nasional

Sumber: halaman **Tabel Harga** di <https://www.bi.go.id/hargapangan>. Halaman ini memakai
komponen DevExtreme yang memanggil endpoint JSON internal. Endpoint ini **tidak terdokumentasi
resmi** dan bisa berubah sewaktu-waktu. Dokumen ini disusun dari rekaman HAR (1 Nov 2026) dan
hasil probe (`src/pihps/probe.py`).

Base: `https://www.bi.go.id/hargapangan/WebSite/TabelHarga/`

Header yang dikirim browser: `X-Requested-With: XMLHttpRequest`,
`Accept: application/json, text/javascript, */*; q=0.01`. Parameter `_=<timestamp>` hanya
cache-buster jQuery, tidak wajib.

Semua respons berbentuk `{"data": [...]}`.

## Halaman sumber

| Halaman | Jenis pasar |
|---|---|
| `/TabelHarga/PasarTradisionalDaerah`, `.../PasarTradisionalKomoditas` | Pasar Tradisional |
| `/TabelHarga/PasarModernDaerah`, `.../PasarModernKomoditas` | Pasar Modern |
| `/TabelHarga/PedagangBesarDaerah`, `.../PedagangBesarKomoditas` | Pedagang Besar |
| `/TabelHarga/ProdusenDaerah`, `.../ProdusenKomoditas` | Produsen |

## Endpoint referensi

| Endpoint | Parameter | Contoh respons |
|---|---|---|
| `GetRefPriceType` | `filter` (opsional, mis. `["id",1]`) | `[{"id":1,"name":"Pasar Tradisional"}]` |
| `GetRefCommodityAndCategory` | – | `[{"id":"cat_1","name":"Beras","cat_id":null,"denomination":"kg","sort":1}, {"id":"com_1","name":"Beras Kualitas Bawah I","cat_id":"cat_1",...}]` |
| `GetRefProvince` | – | `[{"id":1,"name":"Aceh"}, ...]` (34 provinsi) |
| `GetRefRegency` | `price_type_id`, `ref_prov_id` | kosong jika `ref_prov_id` kosong |
| `GetRefMarket` | `price_type_id`, `ref_regency_id` | kosong jika `ref_regency_id` kosong |

Komoditas berbentuk pohon dua level: 10 kategori (`cat_1`..`cat_10`) dan 21 komoditas
(`com_1`..`com_21`). Satuan semua `kg` menurut API (catatan: telur & minyak goreng perlu dicek
apakah benar per kg atau per liter/butir di sumber aslinya).

Daftar provinsi masih 34 (belum memisahkan provinsi hasil pemekaran Papua 2022).

## Endpoint harga: `GetGridDataDaerah`

| Parameter | Nilai |
|---|---|
| `price_type_id` | 1 = Pasar Tradisional (terverifikasi); 2-4 = Modern, Pedagang Besar, Produsen (diverifikasi probe) |
| `comcat_id` | kosong = semua; atau id `cat_x`/`com_x` (dipisah koma) |
| `province_id`, `regency_id`, `market_id` | kosong = agregat nasional; id dipisah koma |
| `tipe_laporan` | 1 = Harian, 4 = Mingguan, 5 = Bulanan, 6 = Grafis (2 & 3 dinonaktifkan di UI) |
| `start_date`, `end_date` | `YYYY-MM-DD` |

Respons berformat **lebar**, satu kolom per tanggal, harga sebagai string ber-pemisah ribuan:

```json
{"data": [
  {"no": "I", "name": "Beras", "level": 1, "26/10/2026": "16,450", "27/10/2026": "16,450"},
  {"no": 1, "name": "Beras Kualitas Bawah I", "level": 2, "26/10/2026": "14,950"}
]}
```

- `level: 1` = baris kategori (rata-rata), `level: 2` = komoditas.
- Hanya hari kerja yang muncul (tanggal 24-25 & 31 Okt tidak ada di respons).
- Nama bisa mengandung spasi berlebih (`"Cabai Merah Keriting "`).

`GetChartDaerah` memakai parameter yang sama dan dipakai untuk mode grafis.

## Temuan probe (run 1 Nov 2026, runner `ubuntu-latest`)

| Temuan | Implikasi |
|---|---|
| Runner GitHub (IP luar negeri) **bisa** mengakses API, HTTP 200 dalam < 1 detik | GitHub Actions layak dipakai sebagai scheduler; tidak perlu runner di Indonesia |
| `GetRefPriceType` tanpa filter: 1 Pasar Tradisional, 2 Pasar Modern, 3 Pedagang Besar, 4 Produsen | Mapping `PRICE_TYPES` terkonfirmasi |
| Data historis tersedia sejak **1 Juni 2017** (awal PIHPS), dengan sebagian nilai kosong di 2017 | Backfill mulai 2017-06-01; staging harus toleran terhadap NULL |
| Rentang 1 bulan ≈ 1,5 detik; rentang **1 tahun timeout** (> 60 detik) | Backfill dipecah per bulan |
| `province_id=13,12` mengembalikan **satu** seri gabungan (rata-rata), bukan per provinsi | Harus satu request per wilayah |
| DKI Jakarta hanya punya 1 kab/kota di PIHPS (Kota Jakarta Pusat) | Cakupan kab/kota per provinsi berbeda-beda; ambil daftar dari `GetRefRegency` |
| `GetRefMarket` untuk regency 34 mengembalikan nama kab/kota, bukan daftar pasar | Level pasar kemungkinan tidak dipublikasikan; pipeline berhenti di level kab/kota |
| `tipe_laporan=4` (mingguan) berfungsi, tanggal = awal minggu | Cukup ambil harian; agregasi mingguan/bulanan dihitung sendiri di dbt |
| Sampel kategori "Beras" Pasar Modern = Pasar Tradisional (16.400) pada tanggal yang sama | Perlu dicek di staging apakah kebetulan atau data modern meniru tradisional |

Estimasi backfill (harian, per bulan, 4 jenis pasar): nasional + 34 provinsi ≈ 4 × 35 × 113 bulan
≈ 16 ribu request; ditambah level kab/kota. Pada 1 request/1,5 detik, perlu dipecah ke beberapa
job paralel/bertahap agar tetap sopan dan di bawah batas 6 jam per job GitHub Actions.
