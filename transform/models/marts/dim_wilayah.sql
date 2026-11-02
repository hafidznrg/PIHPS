{{ config(location=var('out_root') ~ '/marts/dim_wilayah.parquet') }}
-- Dimensi wilayah SCD2 (nasional, provinsi, kab/kota) diturunkan ulang dari seluruh snapshot
-- referensi di raw setiap build, bukan dari dbt snapshot: raw immutable menyimpan histori
-- lengkap sehingga dimensi selalu bisa direkonstruksi tanpa state tambahan.
--
-- Versi baru tercipta bila atribut (nama, provinsi induk) berubah antar-snapshot. Versi
-- pertama berlaku sejak var data_start supaya fakta historis (backfill sejak 2017) tetap
-- tergabung walau snapshot referensi baru ada sejak run pertama extractor.
with snapshot_provinsi as (
    select
        'prov-' || provinsi_id as kode_wilayah,
        'provinsi' as level_wilayah,
        provinsi_id,
        cast(null as integer) as kabkota_id,
        nama,
        _ingest_date as snapshot_date,
        _ingested_at
    from {{ ref('stg_pihps__ref_provinsi') }}
),

snapshot_kabkota as (
    select
        'kab-' || kabkota_id as kode_wilayah,
        'kabkota' as level_wilayah,
        provinsi_id,
        kabkota_id,
        nama,
        _ingest_date as snapshot_date,
        _ingested_at
    from {{ ref('stg_pihps__ref_kabkota') }}
),

-- Jaring pengaman: nama wilayah yang tercatat di manifest file harga (berasal dari
-- referensi di run yang sama). Menjamin setiap wilayah di fakta punya baris dimensi.
snapshot_manifest as (
    select
        case level when 'provinsi' then 'prov-' || level_id else 'kab-' || level_id end
            as kode_wilayah,
        level as level_wilayah,
        coalesce(province_id, try_cast(level_id as integer)) as provinsi_id,
        case level when 'kabkota' then try_cast(level_id as integer) end as kabkota_id,
        trim(case level when 'provinsi' then province_name else regency_name end) as nama,
        ingest_date as snapshot_date,
        fetched_at as _ingested_at
    from {{ ref('stg_pihps__manifest_files') }}
    where ok
        and endpoint = 'GetGridDataDaerah'
        and level in ('provinsi', 'kabkota')
        and coalesce(province_name, regency_name) is not null
),

snapshots as (
    select * from snapshot_provinsi
    union all
    select * from snapshot_kabkota
    union all
    select * from snapshot_manifest
),

-- Satu keadaan per wilayah per hari snapshot (yang terbaru di hari itu).
harian as (
    select *
    from snapshots
    qualify row_number() over (
        partition by kode_wilayah, snapshot_date order by _ingested_at desc, nama
    ) = 1
),

berubah as (
    select
        *,
        md5(concat_ws('|', nama, provinsi_id)) as atribut_hash,
        lag(md5(concat_ws('|', nama, provinsi_id))) over (
            partition by kode_wilayah order by snapshot_date
        ) as atribut_hash_sebelumnya
    from harian
),

versi as (
    select
        *,
        row_number() over (partition by kode_wilayah order by snapshot_date) as versi_ke,
        lead(snapshot_date) over (partition by kode_wilayah order by snapshot_date)
            as mulai_versi_berikutnya
    from berubah
    where atribut_hash_sebelumnya is null or atribut_hash_sebelumnya <> atribut_hash
),

terlihat as (
    select
        kode_wilayah,
        min(snapshot_date) as pertama_terlihat,
        max(snapshot_date) as terakhir_terlihat
    from snapshots
    group by kode_wilayah
),

provinsi_bps as (
    select pihps_provinsi_id, kode_bps from {{ ref('wilayah_provinsi_bps') }}
),

kabkota_bps as (
    select pihps_kabkota_id, kode_bps, nama_bps from {{ ref('wilayah_kabkota_bps') }}
),

wilayah as (
    select
        versi.kode_wilayah,
        versi.level_wilayah,
        versi.provinsi_id,
        versi.kabkota_id,
        versi.nama,
        versi.versi_ke,
        case
            when versi.versi_ke = 1 then cast('{{ var("data_start") }}' as date)
            else versi.snapshot_date
        end as valid_from,
        versi.mulai_versi_berikutnya as valid_to,
        versi.mulai_versi_berikutnya is null as is_current,
        terlihat.pertama_terlihat,
        terlihat.terakhir_terlihat
    from versi
    inner join terlihat using (kode_wilayah)

    union all

    select
        'nasional',
        'nasional',
        null,
        null,
        'Nasional',
        1,
        cast('{{ var("data_start") }}' as date),
        null,
        true,
        null,
        null
)

select
    md5(wilayah.kode_wilayah || '|' || wilayah.valid_from) as wilayah_sk,
    wilayah.kode_wilayah,
    wilayah.level_wilayah,
    wilayah.provinsi_id,
    wilayah.kabkota_id,
    wilayah.nama,
    induk.nama as nama_provinsi,
    case wilayah.level_wilayah
        when 'provinsi' then provinsi_bps.kode_bps
        when 'kabkota' then kabkota_bps.kode_bps
    end as kode_bps,
    provinsi_bps.kode_bps as kode_bps_provinsi,
    kabkota_bps.nama_bps,
    wilayah.versi_ke,
    wilayah.valid_from,
    wilayah.valid_to,
    wilayah.is_current,
    wilayah.pertama_terlihat,
    wilayah.terakhir_terlihat
from wilayah
left join provinsi_bps on wilayah.provinsi_id = provinsi_bps.pihps_provinsi_id
left join kabkota_bps on wilayah.kabkota_id = kabkota_bps.pihps_kabkota_id
-- Nama provinsi induk versi terkini (untuk label kab/kota).
left join (
    select distinct on (provinsi_id) provinsi_id, nama
    from harian
    where level_wilayah = 'provinsi'
    order by provinsi_id, snapshot_date desc
) as induk on wilayah.provinsi_id = induk.provinsi_id
order by wilayah.level_wilayah, wilayah.provinsi_id, wilayah.kabkota_id, wilayah.valid_from
