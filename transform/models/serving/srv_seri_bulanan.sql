-- Rata-rata bulanan per seri sejak awal data (grafik jangka panjang di halaman wilayah).
select
    jenis_pasar_id,
    kode_wilayah,
    komoditas_id,
    cast(date_trunc('month', tanggal) as date) as bulan,
    cast(round(avg(harga)) as bigint) as harga,
    count(*) as hari_data
from {{ ref('srv_harga_bersih') }}
group by all
