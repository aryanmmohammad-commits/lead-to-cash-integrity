select {{ finding('R5', 'deal', 'd.deal_id', 'd.owner_id', "'line-item and recurring charge seats differ'",
  'struct_pack(crm_seats := d.line_item_seats, billing_seats := o.recurring_seats, unit_prices := d.unit_prices)',
  'abs(d.line_item_seats - o.recurring_seats) * abs(cast(d.unit_price * d.rate_to_chf as decimal(38,12)))') }}
from {{ ref('int_deal_context') }} d
join {{ ref('int_order_financials') }} o on o.record_id = d.order_record_id
where d.is_closed_won and d.is_trusted and d.invalid_item_count = 0
  and d.line_item_seats <> o.recurring_seats
