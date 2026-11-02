{#- Akses raw zone. Semua path relatif terhadap var raw_root, sama dengan key di R2. -#}

{% macro raw_glob(pattern) -%}
  {{ var('raw_root').rstrip('/') }}/raw/pihps/{{ pattern }}
{%- endmacro %}

{#- Key R2 dari nama file lokal: buang prefix raw_root. -#}
{% macro raw_key(filename_col) -%}
  substr({{ filename_col }}, {{ (var('raw_root').rstrip('/') ~ '/') | length + 1 }})
{%- endmacro %}

{#-
  Record `data[]` dari file raw yang terdaftar di manifest dengan ok = true.
  File yang ada di disk/R2 tetapi tidak tercatat di manifest mana pun (mis. run yang crash
  sebelum menulis manifest) ikut terbaca oleh glob, tetapi tersaring oleh inner join.
-#}
{% macro raw_records(pattern, endpoint) -%}
  {#- read_json gagal bila glob kosong (mis. run tanpa level kab/kota belum punya
      ref_regency), jadi cek dulu dan kembalikan relasi kosong berskema sama. -#}
  {%- set n_files = 1 -%}
  {%- if execute -%}
    {%- set n_files = run_query("select count(*) from glob('" ~ raw_glob(pattern) ~ "')").columns[0].values()[0] -%}
  {%- endif -%}
  {%- if n_files > 0 %}
  select
    m.*,
    unnest(r.data) as rec
  from read_json(
    '{{ raw_glob(pattern) }}',
    columns = {'data': 'JSON[]'},
    format = 'auto',
    compression = 'gzip',
    filename = true
  ) as r
  inner join {{ ref('stg_pihps__manifest_files') }} as m
    on m.path = {{ raw_key('r.filename') }}
  where m.ok
    and m.endpoint = '{{ endpoint }}'
  {%- else %}
  select m.*, cast(null as json) as rec
  from {{ ref('stg_pihps__manifest_files') }} as m
  where false
  {%- endif %}
{%- endmacro %}

{#- Normalisasi nama untuk pencocokan: trim, spasi ganda, huruf kecil. -#}
{% macro norm_name(col) -%}
  lower(regexp_replace(trim({{ col }}), '\s+', ' ', 'g'))
{%- endmacro %}

{#- '16,450' -> 16450; '', '-', '0' -> NULL. Sama dengan pihps.parse.parse_price. -#}
{% macro parse_harga(col) -%}
  nullif(try_cast(nullif(regexp_replace(trim({{ col }}), '[,.]', '', 'g'), '-') as bigint), 0)
{%- endmacro %}
