-- Semua snapshot GetRefPriceType.
select
    cast(rec ->> 'id' as integer) as jenis_pasar_id,
    trim(rec ->> 'name') as nama,
    run_id as _run_id,
    ingest_date as _ingest_date,
    fetched_at as _ingested_at
from ({{ raw_records("endpoint=ref_price_type/*/*/*.json.gz", "GetRefPriceType") }})
where rec ->> 'id' is not null
