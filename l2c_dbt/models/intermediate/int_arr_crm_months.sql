select d.*, m.month_end, {{ fx_rate('d.currency', 'm.month_end') }} as month_rate_to_chf
from {{ ref('stg_hubspot__deals') }} d
join {{ ref('int_arr_month_ends') }} m
  on d.contract_start <= m.month_end and m.month_end < d.contract_end
where d.is_closed_won and d.amount is not null
  and not exists (
    select 1 from {{ ref('int_source_quarantine') }} q
    where q.source_table = 'hubspot_deals' and q.record_id = d.record_id
  )
