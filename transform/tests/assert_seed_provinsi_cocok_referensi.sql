{{ config(severity='warn') }}
-- Nama provinsi di seed pemetaan BPS harus sama dengan snapshot GetRefProvince terbaru
-- (id PIHPS bisa saja berubah arti). Warn: pemetaan tetap jalan, tetapi perlu ditinjau.
with terbaru as (
    select *
    from {{ ref('stg_pihps__ref_provinsi') }}
    qualify row_number() over (partition by provinsi_id order by _ingested_at desc) = 1
)
select terbaru.provinsi_id, terbaru.nama, seed.nama_pihps
from terbaru
full outer join {{ ref('wilayah_provinsi_bps') }} as seed
    on terbaru.provinsi_id = seed.pihps_provinsi_id
where seed.nama_pihps is distinct from terbaru.nama
