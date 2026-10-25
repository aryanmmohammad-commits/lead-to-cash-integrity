select d.month_end, d.deal_id, d.company_ids, d.currency, d.amount as acv,
    d.month_rate_to_chf as rate_to_chf,
    cast(round(d.amount * d.month_rate_to_chf, 2) as decimal(38, 2)) as arr_chf
from {{ ref('int_arr_crm_months') }} d
where d.month_rate_to_chf is not null and {{ trusted('hubspot_deals', 'd') }}
