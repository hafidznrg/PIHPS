-- Semua snapshot GetRefCommodityAndCategory: pohon kategori (cat_x) -> komoditas (com_x).
select
    rec ->> 'id' as komoditas_id,
    trim(rec ->> 'name') as nama,
    {{ norm_name("rec ->> 'name'") }} as nama_norm,
    rec ->> 'cat_id' as kategori_id,
    rec ->> 'cat_id' is null as is_kategori,
    rec ->> 'denomination' as satuan,
    try_cast(rec ->> 'sort' as integer) as urutan,
    run_id as _run_id,
    ingest_date as _ingest_date,
    fetched_at as _ingested_at
from ({{ raw_records("endpoint=ref_commodity/*/*/*.json.gz", "GetRefCommodityAndCategory") }})
where rec ->> 'id' is not null
