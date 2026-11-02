-- Format lebar GetGridDataDaerah -> panjang, sebelum dedup. Satu baris per
-- (file raw, komoditas, tanggal). Dipisah dari stg_pihps__harga agar tes parsing
-- (harga_raw yang tidak bisa diparse) melihat semua nilai, bukan hanya versi terbaru.
with records as (
    {{ raw_records("endpoint=grid_daerah/*/*/*/*.json.gz", "GetGridDataDaerah") }}
      and m.records > 0
),

cells as (
    select
        records.* exclude (rec),
        trim(rec ->> 'name') as nama_komoditas,
        try_cast(rec ->> 'level' as integer) as level_komoditas,
        rec ->> 'no' as nomor_baris,
        unnest(json_keys(rec)) as kolom,
        rec
    from records
    where json_keys(rec) <> []
)

select
    cast(try_strptime(kolom, '%d/%m/%Y') as date) as tanggal,
    price_type_id as jenis_pasar_id,
    jenis_pasar,
    level as level_wilayah,
    case level
        when 'nasional' then 'nasional'
        when 'provinsi' then 'prov-' || level_id
        when 'kabkota' then 'kab-' || level_id
    end as kode_wilayah,
    case level
        when 'provinsi' then try_cast(level_id as integer)
        when 'kabkota' then province_id
    end as provinsi_id,
    case level when 'kabkota' then try_cast(level_id as integer) end as kabkota_id,
    nama_komoditas,
    {{ norm_name('nama_komoditas') }} as nama_komoditas_norm,
    level_komoditas,
    rec ->> kolom as harga_raw,
    {{ parse_harga('rec ->> kolom') }} as harga,
    run_id as _run_id,
    ingest_date as _ingest_date,
    fetched_at as _ingested_at,
    path as _source_path
from cells
where regexp_matches(kolom, '^\d{2}/\d{2}/\d{4}$')
