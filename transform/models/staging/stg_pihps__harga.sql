{{
  config(
    materialized='external',
    location=var('out_root') ~ '/staging/stg_pihps__harga',
    format='parquet',
    options={'partition_by': 'tahun, bulan', 'overwrite': true}
  )
}}
-- Harga harian format panjang, satu baris per
-- tanggal x jenis_pasar x kode_wilayah x komoditas_id.
-- Dedup *latest wins*: run harian mengambil ulang 7 hari terakhir dan backfill bisa
-- tumpang-tindih; versi dengan _ingested_at terbaru dipakai sehingga revisi BI tertangkap.
with komoditas as (
    -- Pemetaan nama -> id dari semua snapshot referensi. Kategori dan komoditas dipisah
    -- dengan level karena namanya bisa mirip (mis. "Gula Pasir" vs "Gula Pasir Lokal").
    select distinct
        nama_norm,
        case when is_kategori then 1 else 2 end as level_komoditas,
        komoditas_id
    from {{ ref('stg_pihps__ref_komoditas') }}
),

provinsi_bps as (
    select pihps_provinsi_id, kode_bps from {{ ref('wilayah_provinsi_bps') }}
),

kabkota_bps as (
    select pihps_kabkota_id, kode_bps from {{ ref('wilayah_kabkota_bps') }}
),

latest as (
    select *
    from {{ ref('stg_pihps__harga_raw') }}
    qualify row_number() over (
        partition by tanggal, jenis_pasar_id, kode_wilayah, nama_komoditas_norm, level_komoditas
        order by _ingested_at desc, _source_path desc
    ) = 1
)

select
    latest.tanggal,
    latest.jenis_pasar_id,
    latest.jenis_pasar,
    latest.level_wilayah,
    latest.kode_wilayah,
    latest.provinsi_id,
    latest.kabkota_id,
    provinsi_bps.kode_bps as kode_bps_provinsi,
    kabkota_bps.kode_bps as kode_bps_kabkota,
    komoditas.komoditas_id,
    latest.nama_komoditas,
    latest.level_komoditas,
    latest.harga,
    latest.harga_raw,
    latest._run_id,
    latest._ingest_date,
    latest._ingested_at,
    latest._source_path,
    year(latest.tanggal) as tahun,
    month(latest.tanggal) as bulan
from latest
left join komoditas
    on latest.nama_komoditas_norm = komoditas.nama_norm
    and latest.level_komoditas = komoditas.level_komoditas
left join provinsi_bps
    on latest.provinsi_id = provinsi_bps.pihps_provinsi_id
left join kabkota_bps
    on latest.kabkota_id = kabkota_bps.pihps_kabkota_id
order by latest.kode_wilayah, komoditas.komoditas_id, latest.jenis_pasar_id, latest.tanggal
