{% macro source_quarantine() %}
  {% set queries = [] %}
  {% for table, spec in source_specs().items() %}
    {% set relation = ref(staging_name(table)) %}
    {% for column in spec.get('numbers', []) + spec.get('integers', []) + spec.get('dates', []) %}
      {% set reason = 'unparseable_date' if column in spec.get('dates', []) else 'unparseable_amount' %}
      {% set query %}
        select {{ sql_string(table) }} as source_table, s.record_id,
          {{ sql_string(column) }} as "column", s.{{ adapter.quote(column ~ '__raw') }} as raw_value,
          {{ sql_string(reason) }} as reason
        from {{ relation }} s
        where {{ map_value(table, column, 's.' ~ adapter.quote(column ~ '__raw')) }} is not null
          and s.{{ adapter.quote(column) }} is null
      {% endset %}
      {% do queries.append(query) %}
    {% endfor %}
    {% for column in spec.get('ids', []) + spec.get('lists', []) %}
      {% set query %}
        select {{ sql_string(table) }} as source_table, s.record_id,
          {{ sql_string(column) }} as "column", s.{{ adapter.quote(column ~ '__raw') }} as raw_value,
          'id_corrupted_by_excel' as reason
        from {{ relation }} s
        where {% if column in spec.get('lists', []) %}
          exists (select 1 from unnest(s.{{ adapter.quote(column) }}) ids(id)
                  where {{ excel_id('ids.id') }})
        {% else %}{{ excel_id('s.' ~ adapter.quote(column)) }}{% endif %}
      {% endset %}
      {% do queries.append(query) %}
    {% endfor %}
    {% if spec.get('fx') or table == 'hubspot_deals' %}
      {% set date_expression = as_of_date() if spec.get('fx', 'as_of') == 'as_of'
         else 'coalesce(s.' ~ adapter.quote(spec['fx']) ~ ', ' ~ as_of_date() ~ ')' %}
      {% set query %}
        select {{ sql_string(table) }} as source_table, s.record_id, 'currency' as "column",
          s.currency__raw as raw_value, 'no_fx_rate' as reason
        from {{ relation }} s
        where not exists (
          select 1 from {{ ref('int_fx') }} fx
          where fx.currency = s.currency and fx.effective_start <= {{ date_expression }}
            and (fx.effective_end is null or {{ date_expression }} < fx.effective_end)
        )
      {% endset %}
      {% do queries.append(query) %}
    {% endif %}
  {% endfor %}
  {{ queries | join('\nunion all\n') }}
{% endmacro %}

{% test unique_combination(model, columns) %}
  select {% for column in columns %}{{ adapter.quote(column) }}{% if not loop.last %}, {% endif %}{% endfor %}
  from {{ model }}
  group by all
  having count(*) > 1
{% endtest %}
