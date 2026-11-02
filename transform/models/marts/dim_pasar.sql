{{ config(location=var('out_root') ~ '/marts/dim_pasar.parquet') }}
-- Jenis pasar (price_type_id PIHPS). Nama dari GetRefPriceType terbaru, slug dari manifest
-- (fallback: pemetaan tetap di src/pihps/config.py PRICE_TYPES).
with slug as (
    select distinct price_type_id as jenis_pasar_id, jenis_pasar
    from {{ ref('stg_pihps__manifest_files') }}
    where endpoint = 'GetGridDataDaerah' and price_type_id is not null
),

nama as (
    select jenis_pasar_id, nama
    from {{ ref('stg_pihps__ref_jenis_pasar') }}
    qualify row_number() over (partition by jenis_pasar_id order by _ingested_at desc) = 1
)

select
    coalesce(slug.jenis_pasar_id, nama.jenis_pasar_id) as jenis_pasar_id,
    coalesce(slug.jenis_pasar, case coalesce(slug.jenis_pasar_id, nama.jenis_pasar_id)
        when 1 then 'pasar_tradisional'
        when 2 then 'pasar_modern'
        when 3 then 'pedagang_besar'
        when 4 then 'produsen'
    end) as jenis_pasar,
    coalesce(nama.nama, slug.jenis_pasar) as nama_jenis_pasar,
    case coalesce(slug.jenis_pasar_id, nama.jenis_pasar_id)
        when 1 then 'eceran'
        when 2 then 'eceran'
        when 3 then 'grosir'
        when 4 then 'produsen'
    end as rantai_pasok
from slug
full outer join nama on slug.jenis_pasar_id = nama.jenis_pasar_id
order by jenis_pasar_id
