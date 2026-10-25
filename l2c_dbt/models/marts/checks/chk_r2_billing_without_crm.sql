select {{ finding('R2', 'order', 'o.order_number', rule_value('finance_owner_id'), "'billing order has no closedwon CRM deal'",
  'struct_pack(account_number := o.account_number, version := o.version, recurring_mrr := o.recurring_mrr, currency := o.currency)',
  'abs(o.arr_chf)') }}
from {{ ref('int_order_financials') }} o
where is_current and status = {{ rule_value('active_order_status') }}
  and not exists (
    select 1 from {{ ref('stg_younium__orders') }} history
    join {{ ref('stg_hubspot__deals') }} d on d.deal_id = history.hubspot_deal_id and d.is_closed_won
    where history.order_number = o.order_number and history.status <> {{ rule_value('draft_order_status') }}
  )
