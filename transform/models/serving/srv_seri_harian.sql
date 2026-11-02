-- Seri harian N hari terakhir (relatif tanggal acuan) untuk grafik di halaman wilayah.
select b.*
from {{ ref('srv_harga_bersih') }} as b
cross join {{ ref('srv_tanggal_acuan') }} as a
where b.tanggal > a.tanggal_acuan - {{ var('serving_hari_seri_harian') }}
