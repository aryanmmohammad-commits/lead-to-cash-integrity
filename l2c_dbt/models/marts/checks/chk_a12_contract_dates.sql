with evaluated as (
    select d.*, list_filter([
      case when close_date > {{ as_of_date() }} then 'future close date' end,
      case when contract_end <= contract_start then 'end before start' end,
      case when contract_end > contract_start
             and abs(term_months - date_diff('month', contract_start, contract_end)) > {{ rule('term_tolerance_months') }}
           then 'term mismatch' end
    ], lambda reason: reason is not null) as reasons
    from {{ ref('int_deal_context') }} d where is_closed_won
)
select {{ finding('A12', 'deal', 'd.deal_id', 'd.owner_id', "array_to_string(d.reasons, '; ')",
  'struct_pack(reasons := d.reasons, close_date := d.close_date, contract_start := d.contract_start, contract_end := d.contract_end, term_months := d.term_months)') }}
from evaluated d where len(reasons) > 0
