{#- Tes generik buatan sendiri (tanpa paket dbt_utils agar build tidak butuh `dbt deps`). -#}

{#- Kombinasi kolom harus unik. -#}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as jumlah
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{#- Nilai di luar [min_value, max_value] (NULL diabaikan). -#}
{% test dalam_rentang(model, column_name, min_value=none, max_value=none) %}
select *
from {{ model }}
where {{ column_name }} is not null
  and (
    {%- if min_value is not none %} {{ column_name }} < {{ min_value }} {% else %} false {% endif -%}
    or
    {%- if max_value is not none %} {{ column_name }} > {{ max_value }} {% else %} false {% endif -%}
  )
{% endtest %}
