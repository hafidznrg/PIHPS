{{ config(severity='warn', warn_if='>0') }}
-- Lonjakan antar-hari publikasi: harga naik > 3x atau turun < 1/3 dibanding hari
-- sebelumnya untuk seri yang sama. Biasanya salah input di sumber; warn untuk ditinjau.
with seri as (
    select
        *,
        lag(harga) over (
            partition by jenis_pasar_id, kode_wilayah, komoditas_id order by tanggal
        ) as harga_sebelumnya
    from {{ ref('fct_harga_harian') }}
)
select tanggal, jenis_pasar_id, kode_wilayah, komoditas_id, harga_sebelumnya, harga
from seri
where harga_sebelumnya is not null
  and (harga > 3 * harga_sebelumnya or harga * 3 < harga_sebelumnya)
