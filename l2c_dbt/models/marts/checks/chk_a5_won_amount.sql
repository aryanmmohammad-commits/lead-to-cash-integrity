select {{ finding('A5', 'deal', 'd.deal_id', 'd.owner_id', "'blank or zero won amount'",
  'struct_pack(amount := d.amount, currency := d.currency)') }}
from {{ ref('int_deal_context') }} d
where is_closed_won and ({{ text_value('amount__raw') }} is null or amount = 0)
