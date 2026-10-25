select
    currency,
    date as rate_date,
    date as effective_start,
    lead(date) over (partition by currency order by date) as effective_end,
    rate_to_chf
from {{ ref('stg_ref__fx_rates') }}
where is_parse_valid and rate_to_chf > 0
