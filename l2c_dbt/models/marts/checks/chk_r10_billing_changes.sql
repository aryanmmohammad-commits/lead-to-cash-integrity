with changes as (
    select *, lag(recurring_mrr) over (partition by order_number order by version) as previous_mrr
    from {{ ref('int_order_financials') }}
    where status <> {{ rule_value('draft_order_status') }}
)
select {{ finding('R10', 'order_version', 'o.record_id', rule_value('finance_owner_id'), "'billing value changed without a CRM deal'",
  'struct_pack(order_number := o.order_number, version := o.version, previous_mrr := o.previous_mrr, recurring_mrr := o.recurring_mrr, currency := o.currency)',
  'abs(o.recurring_mrr - o.previous_mrr) * ' ~ rule('months_per_year') ~ ' * o.rate_to_chf') }}
from changes o
where version > {{ rule('initial_order_version') }} and hubspot_deal_id is null
  and recurring_mrr <> previous_mrr
