select month_end::varchar as record_id from {{ ref('int_arr_month_ends') }}
where month_end <> last_day(month_end) or month_end > last_day({{ as_of_date() }})
union all
select 'calendar length' where
    (select count(*) from {{ ref('int_arr_month_ends') }}) <> {{ rule('arr_months') }}
{% for model in ['arr_billing_monthly', 'arr_crm_monthly'] %}
union all
select month_end::varchar from {{ ref(model) }} a
where not exists (select 1 from {{ ref('int_arr_month_ends') }} m where m.month_end = a.month_end)
  or arr_chf <> round(arr_chf, 2)
{% endfor %}
