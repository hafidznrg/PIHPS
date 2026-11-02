-- Setiap nilai harga di raw yang bukan penanda kosong harus bisa diparse menjadi angka.
-- Gagal = format baru dari sumber (mis. desimal, satuan) yang perlu ditangani di staging.
select _source_path, tanggal, nama_komoditas, harga_raw
from {{ ref('stg_pihps__harga_raw') }}
where harga is null
  and trim(coalesce(harga_raw, '')) not in ('', '-', '0')
