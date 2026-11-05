{{ config(materialized='table') }}
-- Satu baris per file di setiap manifest run (raw/pihps/_manifests/**/_manifest.json).
-- Manifest adalah sumber kebenaran staging: hanya file dengan ok = true yang dibaca.
-- Tabel (bukan view): dipakai banyak model & tes sekaligus; sebagai view setiap pemakai
-- mem-parse ulang semua manifest JSON (buffer besar per thread -> tekanan memori).
with manifests as (
    select
        run_id,
        cast(ingest_date as date) as ingest_date,
        status as run_status,
        files
    from read_json(
        '{{ raw_glob("_manifests/*/*/_manifest.json") }}',
        columns = {
            'run_id': 'VARCHAR',
            'ingest_date': 'VARCHAR',
            'status': 'VARCHAR',
            'files': 'JSON[]'
        },
        format = 'auto',
        maximum_object_size = 268435456
    )
),

files as (
    select run_id, ingest_date, run_status, unnest(files) as f
    from manifests
)

select
    run_id,
    ingest_date,
    run_status,
    f ->> 'path' as path,
    f ->> 'endpoint' as endpoint,
    f ->> 'jenis_pasar' as jenis_pasar,
    f ->> 'level' as level,
    f ->> 'level_id' as level_id,
    try_cast(f ->> 'province_id' as integer) as province_id,
    f ->> 'province_name' as province_name,
    try_cast(f ->> 'regency_id' as integer) as regency_id,
    f ->> 'regency_name' as regency_name,
    coalesce(
        try_cast(f -> 'params' ->> 'price_type_id' as integer),
        case f ->> 'jenis_pasar'
            when 'pasar_tradisional' then 1
            when 'pasar_modern' then 2
            when 'pedagang_besar' then 3
            when 'produsen' then 4
        end
    ) as price_type_id,
    try_cast(f -> 'params' ->> 'start_date' as date) as params_start_date,
    try_cast(f -> 'params' ->> 'end_date' as date) as params_end_date,
    cast(f ->> 'fetched_at' as timestamptz) as fetched_at,
    f ->> 'sha256' as sha256,
    try_cast(f ->> 'records' as integer) as records,
    coalesce(try_cast(f ->> 'ok' as boolean), false) as ok,
    f ->> 'error' as error
from files
