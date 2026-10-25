{% for check_id, model in check_models().items() %}
select * from {{ ref(model) }}
{% if check_id == 'P' %}where check_id <> 'P'{% endif %}
{% if not loop.last %}union all{% endif %}
{% endfor %}
