select {{ finding('R9', 'order', 'o.order_number', rule_value('finance_owner_id'), "'new deal pushed to a second billing order'",
  'struct_pack(deal_id := d.deal_id, primary_order := d.order_number, duplicate_order := o.order_number, recurring_mrr := o.recurring_mrr)',
  'abs(o.arr_chf)') }}
from {{ ref('int_deal_context') }} d,
     unnest(d.duplicate_order_numbers) duplicates(order_number)
join {{ ref('int_order_financials') }} o on o.order_number = duplicates.order_number and o.is_current
where d.motion = {{ rule_value('new_deal_motion') }} and d.is_trusted
