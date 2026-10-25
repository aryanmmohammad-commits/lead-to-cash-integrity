with charges as (
    select order_number, version, sum(mrr) as recurring_mrr, sum(quantity) as recurring_seats
    from {{ ref('stg_younium__order_charges') }} c
    where charge_type = {{ rule_value('recurring_charge_type') }}
      and {{ trusted('younium_order_charges', 'c') }}
    group by order_number, version
)
select o.*, coalesce(c.recurring_mrr, 0) as recurring_mrr,
    coalesce(c.recurring_seats, 0) as recurring_seats,
    {{ fx_rate('o.currency') }} as rate_to_chf,
    coalesce(c.recurring_mrr, 0) * {{ rule('months_per_year') }} * {{ fx_rate('o.currency') }} as arr_chf,
    coalesce(company.owner_id, {{ rule_value('unassigned_owner_id') }}) as owner_id,
    coalesce(company.has_open_renewal, false) as has_open_renewal
from {{ ref('int_order_versions') }} o
left join charges c using (order_number, version)
left join {{ ref('int_company_context') }} company using (company_id)
