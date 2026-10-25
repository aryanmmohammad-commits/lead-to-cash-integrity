select {{ finding('R1', 'deal', 'd.deal_id', 'd.owner_id',
  "case when d.has_draft_order then 'only a draft order' else 'no order' end",
  'struct_pack(amount := d.amount, currency := d.currency, contract_start := d.contract_start, has_draft_order := d.has_draft_order)',
  'abs(d.amount * d.rate_to_chf)') }}
from {{ ref('int_deal_context') }} d
where is_closed_won and motion = {{ rule_value('new_deal_motion') }} and not is_matched
  and is_trusted and not has_untrusted_order
  and date_diff('day', contract_start, {{ as_of_date() }}) > {{ rule('won_not_billed_days') }}
