-- Semua snapshot GetRefProvince (id provinsi PIHPS, bukan kode BPS).
select
    cast(rec ->> 'id' as integer) as provinsi_id,
    trim(rec ->> 'name') as nama,
    run_id as _run_id,
    ingest_date as _ingest_date,
    fetched_at as _ingested_at
from ({{ raw_records("endpoint=ref_province/*/*/*.json.gz", "GetRefProvince") }})
where rec ->> 'id' is not null
