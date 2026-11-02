-- Setiap hari publikasi PIHPS harus punya harga nasional pasar tradisional untuk semua
-- kategori yang pernah muncul di hari lain (sentinel F1, sekarang di layer staging).
{{ config(severity='warn') }}
with nasional as (
    select tanggal, komoditas_id
    from {{ ref('fct_harga_harian') }}
    where kode_wilayah = 'nasional' and jenis_pasar_id = 1 and level_komoditas = 1
),
hari as (select distinct tanggal from nasional),
kategori as (select distinct komoditas_id from nasional)
select hari.tanggal, kategori.komoditas_id
from hari
cross join kategori
left join nasional using (tanggal, komoditas_id)
where nasional.tanggal is null
