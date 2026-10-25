select {{ finding('R4', 'deal', 'd.deal_id', 'd.owner_id', "'contract and billing start dates differ'",
  'struct_pack(contract_start := d.contract_start, billing_start := d.order_effective_start)') }}
from {{ ref('int_deal_context') }} d
where is_closed_won and is_matched and is_trusted
  and abs(date_diff('day', contract_start, order_effective_start)) > {{ rule('start_date_tolerance_days') }}
