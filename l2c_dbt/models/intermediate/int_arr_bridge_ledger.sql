with order_contributions as (
    select 'order'::varchar as object_type, order_number as record_id,
        remaining_category as category, remaining_chf as amount_chf
    from {{ ref('int_arr_bridge_orders') }}
    union all
    select 'order', order_number, 'billing_only_change', billing_change_chf
    from {{ ref('int_arr_bridge_orders') }} where billing_change_chf <> 0
), unmatched_crm as (
    select 'deal'::varchar as object_type, c.deal_id as record_id,
        case when exists (
               select 1 from {{ ref('stg_younium__orders') }} o
               where o.hubspot_deal_id = c.deal_id
                 and o.status <> {{ rule_value('draft_order_status') }}
                 and (not exists (select 1 from {{ ref('int_order_versions') }} valid
                                  where valid.record_id = o.record_id)
                      or exists (select 1 from {{ ref('quarantine') }} q
                                 where q.source_table = 'younium_orders'
                                   and q.record_id = o.record_id))
             ) then 'quarantined'
             when exists (select 1 from {{ ref('chk_r6_unbilled_changes') }} r
                          where r.record_id = c.deal_id) then 'value_mismatch'
             when c.motion = {{ rule_value('new_deal_motion') }}
               then case when exists (select 1 from {{ ref('chk_r1_won_not_billed') }} r
                                      where r.record_id = c.deal_id)
                         then 'won_not_billed' else 'not_yet_billed' end
             else 'unexplained' end as category,
        -c.arr_chf as amount_chf
    from (
      select a.*, d.motion from {{ ref('arr_crm_monthly') }} a
      join {{ ref('stg_hubspot__deals') }} d using (deal_id)
      where a.month_end = last_day({{ as_of_date() }})
    ) c
    where not exists (select 1 from {{ ref('int_deal_order_match') }} m
                      where m.deal_id = c.deal_id and m.is_matched)
), unvalued as (
    -- Unknown FX/amounts stay unvalued. A zero contribution exposes the quarantine
    -- without inventing CHF; any reliable opposite side is classified above.
    select distinct 'deal'::varchar as object_type, d.deal_id as record_id,
        'quarantined'::varchar as category, 0::decimal(38,2) as amount_chf
    from {{ ref('stg_hubspot__deals') }} d
    join {{ ref('quarantine') }} q
      on q.source_table = 'hubspot_deals' and q.record_id = d.record_id
    where d.is_closed_won
)
select last_day({{ as_of_date() }})::date as month_end, object_type, record_id, category,
    sum(amount_chf)::decimal(38,2) as amount_chf
from (
    select * from order_contributions
    union all select * from unmatched_crm
    union all select * from unvalued
) contributions
group by all
