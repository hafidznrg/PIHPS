{{ config(severity='warn', warn_if='>0') }}
-- Lonjakan antar-hari publikasi berurutan: harga naik > 3x atau turun < 1/3 dibanding
-- titik sebelumnya di seri yang sama, dengan jeda <= 7 hari (seri berjeda, mis. backfill
-- yang belum lengkap, bukan lonjakan). Biasanya salah input di sumber; warn untuk ditinjau.
with seri as (
    select
        *,
        lag(harga) over w as harga_sebelumnya,
        lag(tanggal) over w as tanggal_sebelumnya
    from {{ ref('fct_harga_harian') }}
    window w as (partition by jenis_pasar_id, kode_wilayah, komoditas_id order by tanggal)
)
select
    jenis_pasar_id, kode_wilayah, komoditas_id, tanggal_sebelumnya, harga_sebelumnya,
    tanggal, harga
from seri
where harga_sebelumnya is not null
  and tanggal - tanggal_sebelumnya <= 7
  and (harga > 3 * harga_sebelumnya or harga * 3 < harga_sebelumnya)
