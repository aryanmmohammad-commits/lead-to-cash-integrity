select {{ finding('A6', 'deal', 'd.deal_id', 'd.owner_id', "'missing contract fields'",
  'struct_pack(contract_start := d.contract_start, contract_end := d.contract_end, term_months := d.term_months)') }}
from {{ ref('int_deal_context') }} d
where is_closed_won and ({{ text_value('contract_start__raw') }} is null
  or {{ text_value('contract_end__raw') }} is null or {{ text_value('term_months__raw') }} is null)
