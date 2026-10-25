{% for check_id, model in check_models().items() %}
select check_id, record_id from {{ ref(model) }}
where check_id is null or not list_contains(
    {{ string_list((rule('check_catalog').keys() | list) + (rule('push_check_ids').values() | list)) }}, check_id)
  or not list_contains({{ string_list(rule('severity_allowed')) }}, severity)
  or severity is null or object_type is null or record_id is null or owner_id is null
  or reason is null or details is null or money_at_risk_chf < 0
{% if not loop.last %}union all{% endif %}
{% endfor %}
