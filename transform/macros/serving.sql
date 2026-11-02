{#- Perubahan persen dua desimal; NULL bila pembanding kosong/nol. -#}
{% macro persen(baru, lama) -%}
    round(100.0 * ({{ baru }} - {{ lama }}) / nullif({{ lama }}, 0), 2)
{%- endmacro %}
