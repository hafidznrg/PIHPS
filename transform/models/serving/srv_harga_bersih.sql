{{ config(materialized='view') }}
-- Sel fakta tanpa outlier, + atribut wilayah terkini. Dasar semua model serving.
select
    f.tanggal,
    f.jenis_pasar_id,
    f.kode_wilayah,
    f.komoditas_id,
    f.level_komoditas,
    f.harga
from {{ ref('fct_harga_harian') }} as f
where not f.is_outlier
