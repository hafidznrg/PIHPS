{{
  config(
    location=var('out_root') ~ '/marts/fct_harga_harian',
    options={'partition_by': 'tahun', 'overwrite': true}
  )
}}
-- Fakta harga harian. Grain: tanggal x jenis_pasar x wilayah x komoditas (termasuk baris
-- kategori = rata-rata BI; bedakan lewat dim_komoditas.tipe). Hanya sel yang berharga:
-- nilai kosong ('-') tetap ada di staging untuk audit.
with harga as (
    select *
    from {{ ref('stg_pihps__harga') }}
    where harga is not null
),

wilayah as (
    select wilayah_sk, kode_wilayah, valid_from, valid_to
    from {{ ref('dim_wilayah') }}
)

select
    harga.tanggal,
    harga.jenis_pasar_id,
    harga.kode_wilayah,
    wilayah.wilayah_sk,
    harga.komoditas_id,
    harga.level_komoditas,
    harga.harga,
    harga._ingested_at,
    harga._run_id,
    harga.tahun
from harga
left join wilayah
    on harga.kode_wilayah = wilayah.kode_wilayah
    and harga.tanggal >= wilayah.valid_from
    and (wilayah.valid_to is null or harga.tanggal < wilayah.valid_to)
order by harga.kode_wilayah, harga.komoditas_id, harga.jenis_pasar_id, harga.tanggal
