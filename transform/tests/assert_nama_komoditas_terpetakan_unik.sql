-- Satu nama komoditas (ternormalisasi) per level harus memetakan ke tepat satu id di seluruh
-- snapshot referensi; jika tidak, dedup dan pemetaan di stg_pihps__harga menjadi ambigu.
select nama_norm, is_kategori, count(distinct komoditas_id) as jumlah_id
from {{ ref('stg_pihps__ref_komoditas') }}
group by nama_norm, is_kategori
having count(distinct komoditas_id) > 1
