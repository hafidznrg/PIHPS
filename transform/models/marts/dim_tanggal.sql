{{ config(location=var('out_root') ~ '/marts/dim_tanggal.parquet') }}
-- Kalender harian sejak awal data PIHPS sampai tanggal data terakhir (atau hari ini).
-- Hari kerja = Senin-Jumat di luar libur nasional & cuti bersama (seed hari_libur).
with batas as (
    select greatest(coalesce(max(tanggal), current_date), current_date) as akhir
    from {{ ref('stg_pihps__harga') }}
),

tanggal as (
    select cast(unnest(generate_series(
        cast('{{ var("data_start") }}' as date), batas.akhir, interval 1 day
    )) as date) as tanggal
    from batas
),

libur as (
    select tanggal, nama, jenis from {{ ref('hari_libur') }}
),

-- Hari publikasi PIHPS = ada harga nasional pasar tradisional (hanya hari kerja).
terbit as (
    select distinct tanggal
    from {{ ref('stg_pihps__harga') }}
    where kode_wilayah = 'nasional' and jenis_pasar_id = 1 and harga is not null
)

select
    tanggal.tanggal,
    year(tanggal.tanggal) as tahun,
    quarter(tanggal.tanggal) as kuartal,
    month(tanggal.tanggal) as bulan,
    ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus',
     'September', 'Oktober', 'November', 'Desember'][month(tanggal.tanggal)] as nama_bulan,
    day(tanggal.tanggal) as hari_ke,
    isodow(tanggal.tanggal) as hari_dalam_minggu,
    ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'][isodow(tanggal.tanggal)]
        as nama_hari,
    isodow(tanggal.tanggal) >= 6 as is_akhir_pekan,
    libur.tanggal is not null as is_hari_libur,
    libur.jenis as jenis_libur,
    libur.nama as nama_libur,
    isodow(tanggal.tanggal) <= 5 and libur.tanggal is null as is_hari_kerja,
    isoyear(tanggal.tanggal) as tahun_iso,
    week(tanggal.tanggal) as minggu_iso,
    cast(date_trunc('week', tanggal.tanggal) as date) as awal_minggu,
    cast(date_trunc('month', tanggal.tanggal) as date) as awal_bulan,
    terbit.tanggal is not null as ada_data_pihps
from tanggal
left join terbit on tanggal.tanggal = terbit.tanggal
left join libur on tanggal.tanggal = libur.tanggal
order by tanggal.tanggal
