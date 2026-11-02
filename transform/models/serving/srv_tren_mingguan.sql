-- Rata-rata mingguan nasional per jenis pasar sejak awal data (halaman komoditas:
-- tren jangka panjang dan rantai pasok produsen -> pedagang besar -> eceran).
select
    jenis_pasar_id,
    komoditas_id,
    cast(date_trunc('week', tanggal) as date) as minggu,
    cast(round(avg(harga)) as bigint) as harga,
    count(*) as hari_data
from {{ ref('srv_harga_bersih') }}
where kode_wilayah = 'nasional'
group by all
