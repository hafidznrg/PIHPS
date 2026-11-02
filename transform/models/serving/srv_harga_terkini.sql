-- Harga terbaru per seri (jenis_pasar x wilayah x komoditas) dan pembandingnya:
-- hari publikasi sebelumnya, seminggu/sebulan/setahun lalu (as-of: nilai terakhir pada atau
-- sebelum tanggal pembanding), dan rata-rata nasional di jenis pasar yang sama.
with seri as (
    select
        *,
        lag(harga) over w as harga_sebelumnya,
        lag(tanggal) over w as tanggal_sebelumnya
    from {{ ref('srv_harga_bersih') }}
    window w as (partition by jenis_pasar_id, kode_wilayah, komoditas_id order by tanggal)
),

terbaru as (
    select *
    from seri
    qualify row_number() over (
        partition by jenis_pasar_id, kode_wilayah, komoditas_id order by tanggal desc
    ) = 1
),

{% set pembanding = {'7h': 7, '30h': 30, '1th': 365} %}
{% for nama, hari in pembanding.items() %}
lalu_{{ nama }} as (
    select t.jenis_pasar_id, t.kode_wilayah, t.komoditas_id, b.tanggal, b.harga
    from terbaru as t
    asof left join {{ ref('srv_harga_bersih') }} as b
        on t.jenis_pasar_id = b.jenis_pasar_id
        and t.kode_wilayah = b.kode_wilayah
        and t.komoditas_id = b.komoditas_id
        and t.tanggal - {{ hari }} >= b.tanggal
),
{% endfor %}

acuan as (select tanggal_acuan from {{ ref('srv_tanggal_acuan') }}),

gabung as (
    select
        t.jenis_pasar_id,
        t.kode_wilayah,
        t.komoditas_id,
        t.level_komoditas,
        t.tanggal,
        t.harga,
        t.tanggal_sebelumnya,
        t.harga_sebelumnya,
        {% for nama, hari in pembanding.items() %}
        -- pembanding yang terlalu jauh (seri berjeda) diabaikan
        case when l{{ loop.index }}.tanggal >= t.tanggal - {{ hari + 14 }}
            then l{{ loop.index }}.tanggal end as tanggal_{{ nama }},
        case when l{{ loop.index }}.tanggal >= t.tanggal - {{ hari + 14 }}
            then l{{ loop.index }}.harga end as harga_{{ nama }},
        {% endfor %}
        t.tanggal >= acuan.tanggal_acuan - {{ var('serving_hari_aktif') }} as is_aktif
    from terbaru as t
    cross join acuan
    {% for nama, hari in pembanding.items() %}
    left join lalu_{{ nama }} as l{{ loop.index }}
        using (jenis_pasar_id, kode_wilayah, komoditas_id)
    {% endfor %}
),

nasional as (
    select jenis_pasar_id, komoditas_id, tanggal, harga as harga_nasional
    from gabung
    where kode_wilayah = 'nasional'
)

select
    g.*,
    {{ persen('g.harga', 'g.harga_sebelumnya') }} as perubahan_pct_sebelumnya,
    {{ persen('g.harga', 'g.harga_7h') }} as perubahan_pct_7h,
    {{ persen('g.harga', 'g.harga_30h') }} as perubahan_pct_30h,
    {{ persen('g.harga', 'g.harga_1th') }} as perubahan_pct_1th,
    case
        when g.harga_7h is null then null
        when abs({{ persen('g.harga', 'g.harga_7h') }}) < {{ var('serving_ambang_tetap_pct') }}
            then 'tetap'
        when g.harga > g.harga_7h then 'naik'
        else 'turun'
    end as arah_7h,
    -- dibanding rata-rata nasional pada tanggal yang sama (hanya bila tanggalnya sama)
    case when n.tanggal = g.tanggal and g.kode_wilayah <> 'nasional'
        then {{ persen('g.harga', 'n.harga_nasional') }} end as selisih_pct_nasional
from gabung as g
left join nasional as n using (jenis_pasar_id, komoditas_id)
