select {{ finding('R6', 'deal', 'd.deal_id', 'd.owner_id', "'won change deal has no non-draft billing version'",
  'struct_pack(motion := d.motion, contract_start := d.contract_start, amount := d.amount, currency := d.currency)',
  'abs(d.amount * d.rate_to_chf)') }}
from {{ ref('int_deal_context') }} d
where is_closed_won and list_contains({{ string_list(rule('change_deal_motions')) }}, motion)
  and not is_matched and is_trusted and not has_untrusted_order
  and date_diff('day', contract_start, {{ as_of_date() }}) > {{ rule('won_not_billed_days') }}
