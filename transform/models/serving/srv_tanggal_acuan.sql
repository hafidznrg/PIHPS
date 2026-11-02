-- Tanggal acuan situs = tanggal harga terbaru nasional pasar tradisional (seri acuan sentinel).
-- Semua "hari ini", "seminggu lalu", dan status aktif dihitung relatif terhadap tanggal ini.
select max(tanggal) as tanggal_acuan
from {{ ref('srv_harga_bersih') }}
where kode_wilayah = 'nasional' and jenis_pasar_id = 1
