{% set denominators = denominator_queries() %}
with denominators as (
    {% for check_id, definition in rule('check_catalog').items() %}
    {% if check_id != 'Q' %}
      {% if definition['denominator'] not in denominators %}
        {{ exceptions.raise_compiler_error('rules.check_catalog.' ~ check_id ~ '.denominator is unknown') }}
      {% endif %}
      select {{ sql_string(check_id) }} as check_id,
             {{ sql_string(definition['description']) }} as description,
             ({{ denominators[definition['denominator']] }})::bigint as rows_checked
      union all
    {% endif %}
    {% endfor %}
    select 'Q' as check_id, {{ sql_string(rule('check_catalog')['Q']['description']) }} as description,
      ({% for table in source_specs() %}(select count(*) from {{ ref(staging_name(table)) }})
        {% if not loop.last %}+{% endif %}{% endfor %})::bigint as rows_checked
), failures as (
    select case when list_contains({{ string_list(rule('push_check_ids').values() | list) }}, check_id)
                then 'P' else check_id end as check_id,
           count(distinct (object_type,
             case when check_id = 'R9' then json_extract_string(details, '$.deal_id')
                  else record_id end))::bigint as rows_failed
    from {{ ref('exceptions') }} group by 1
    union all
    select 'Q', count(distinct (source_table, record_id))::bigint from {{ ref('quarantine') }}
)
select d.check_id, d.description, d.rows_checked, coalesce(f.rows_failed, 0) as rows_failed,
    case when rows_checked = 0 then 1.0
         else round(1.0 - coalesce(f.rows_failed, 0)::decimal / rows_checked,
                    {{ rule('scorecard_decimals') }}) end as pass_rate
from denominators d left join failures f using (check_id)
