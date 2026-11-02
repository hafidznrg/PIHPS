-- Semua snapshot GetRefRegency, per jenis pasar per provinsi (cakupan beda antar jenis pasar).
select
    cast(rec ->> 'id' as integer) as kabkota_id,
    trim(rec ->> 'name') as nama,
    province_id as provinsi_id,
    price_type_id as jenis_pasar_id,
    run_id as _run_id,
    ingest_date as _ingest_date,
    fetched_at as _ingested_at
from ({{ raw_records("endpoint=ref_regency/*/*/*/*.json.gz", "GetRefRegency") }})
where rec ->> 'id' is not null
