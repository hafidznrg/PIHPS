{{ config(location=var('out_root') ~ '/marts/dim_komoditas.parquet') }}
-- Pohon komoditas dua level (10 kategori cat_x, 21 komoditas com_x) dari snapshot referensi
-- terbaru, ditambah HET/harga acuan yang sedang berlaku dari seed het_komoditas.
with terbaru as (
    select *
    from {{ ref('stg_pihps__ref_komoditas') }}
    qualify row_number() over (partition by komoditas_id order by _ingested_at desc) = 1
),

het_berlaku as (
    select *
    from {{ ref('het_komoditas') }}
    where berlaku_mulai <= current_date
        and (berlaku_sampai is null or berlaku_sampai >= current_date)
    qualify row_number() over (partition by komoditas_id order by berlaku_mulai desc) = 1
)

select
    terbaru.komoditas_id,
    terbaru.nama as nama_komoditas,
    case when terbaru.is_kategori then 'kategori' else 'komoditas' end as tipe,
    case when terbaru.is_kategori then 1 else 2 end as level_komoditas,
    coalesce(terbaru.kategori_id, terbaru.komoditas_id) as kategori_id,
    kategori.nama as nama_kategori,
    terbaru.satuan,
    terbaru.urutan,
    het_berlaku.het as het,
    het_berlaku.satuan as het_satuan,
    het_berlaku.berlaku_mulai as het_berlaku_mulai,
    het_berlaku.sumber as het_sumber,
    terbaru._ingested_at as _snapshot_at
from terbaru
left join terbaru as kategori
    on coalesce(terbaru.kategori_id, terbaru.komoditas_id) = kategori.komoditas_id
left join het_berlaku on terbaru.komoditas_id = het_berlaku.komoditas_id
order by level_komoditas, terbaru.urutan
