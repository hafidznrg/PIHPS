-- Daftar wilayah untuk pemilih di web: versi dimensi terkini + jenis pasar yang punya data
-- aktif. Wilayah tanpa satu pun seri harga tidak ikut.
with cakupan as (
    select
        kode_wilayah,
        list(distinct jenis_pasar_id order by jenis_pasar_id)
            filter (where is_aktif) as jenis_pasar_aktif,
        list(distinct jenis_pasar_id order by jenis_pasar_id) as jenis_pasar,
        max(tanggal) as tanggal_terakhir
    from {{ ref('srv_harga_terkini') }}
    group by kode_wilayah
)

select
    w.kode_wilayah,
    w.level_wilayah,
    w.nama,
    w.provinsi_id,
    w.nama_provinsi,
    case w.level_wilayah when 'nasional' then null else 'prov-' || w.provinsi_id end
        as kode_provinsi,
    w.kode_bps,
    c.jenis_pasar,
    coalesce(c.jenis_pasar_aktif, []) as jenis_pasar_aktif,
    c.tanggal_terakhir,
    len(coalesce(c.jenis_pasar_aktif, [])) > 0 as is_aktif
from {{ ref('dim_wilayah') }} as w
inner join cakupan as c using (kode_wilayah)
where w.is_current
