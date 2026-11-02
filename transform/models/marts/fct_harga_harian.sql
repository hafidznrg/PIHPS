{{
  config(
    location=var('out_root') ~ '/marts/fct_harga_harian',
    options={'partition_by': 'tahun', 'overwrite': true}
  )
}}
-- Fakta harga harian. Grain: tanggal x jenis_pasar x wilayah x komoditas (termasuk baris
-- kategori = rata-rata BI; bedakan lewat dim_komoditas.tipe). Hanya sel yang berharga:
-- nilai kosong ('-') tetap ada di staging untuk audit.
--
-- is_outlier MENANDAI (tidak membuang) dugaan salah input di sumber, mis. digit kurang/lebih
-- satu (13.900 vs 139.000) atau Rp100 untuk beras: harga < outlier_harga_min atau
-- > outlier_harga_max (salah input berkepanjangan yang mencemari median), atau menyimpang
-- lebih dari outlier_faktor x dari median jendela +-outlier_jendela hari publikasi di seri yang
-- sama (median tahan terhadap satu-dua nilai salah). Serving memakai sel tanpa outlier.
with harga as (
    select
        *,
        median(harga) over jendela as harga_median_sekitar,
        count(*) over jendela as jumlah_tetangga
    from {{ ref('stg_pihps__harga') }}
    where harga is not null
    window jendela as (
        partition by jenis_pasar_id, kode_wilayah, komoditas_id
        order by tanggal
        rows between {{ var('outlier_jendela') }} preceding
            and {{ var('outlier_jendela') }} following
    )
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
    case
        when harga.harga < {{ var('outlier_harga_min') }} then true
        when harga.harga > {{ var('outlier_harga_max') }} then true
        when harga.jumlah_tetangga < {{ var('outlier_min_tetangga') }} then false
        else harga.harga > {{ var('outlier_faktor') }} * harga.harga_median_sekitar
            or harga.harga * {{ var('outlier_faktor') }} < harga.harga_median_sekitar
    end as is_outlier,
    cast(round(harga.harga_median_sekitar) as bigint) as harga_median_sekitar,
    harga._ingested_at,
    harga._run_id,
    harga.tahun
from harga
left join wilayah
    on harga.kode_wilayah = wilayah.kode_wilayah
    and harga.tanggal >= wilayah.valid_from
    and (wilayah.valid_to is null or harga.tanggal < wilayah.valid_to)
order by harga.kode_wilayah, harga.komoditas_id, harga.jenis_pasar_id, harga.tanggal
