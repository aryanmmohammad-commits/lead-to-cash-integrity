-- Assign each valued CRM deal to its single matched order. Duplicate pushes
-- retain only billing ARR; upsells/renewals can share the original order.
with billing as (
    select * from {{ ref('arr_billing_monthly') }}
    where month_end = last_day({{ as_of_date() }})
), crm as (
    select m.order_number, count(*) as crm_deal_count, sum(c.arr_chf) as crm_arr_chf
    from {{ ref('arr_crm_monthly') }} c
    join {{ ref('int_deal_order_match') }} m on m.deal_id = c.deal_id and m.is_matched
    where c.month_end = last_day({{ as_of_date() }})
    group by m.order_number
), evidence as (
    select m.order_number,
        bool_or(d.is_closed_won) as has_won_deal,
        bool_or(d.is_closed_won and (d.amount is null or d.contract_start is null
                or d.contract_end is null or d.contract_end <= d.contract_start))
            as has_unvalued_crm_contract,
        bool_or(exists (select 1 from {{ ref('exceptions') }} e
                        where e.record_id = d.deal_id and e.object_type = 'deal'
                          and e.check_id in ('R3', 'R5', 'R6'))) as has_value_mismatch,
        bool_or(exists (select 1 from {{ ref('chk_r4_start_dates') }} e
                        where e.record_id = d.deal_id)) as has_timing_mismatch
    from {{ ref('int_deal_order_match') }} m
    join {{ ref('stg_hubspot__deals') }} d using (deal_id)
    where m.is_matched
    group by m.order_number
), quarantined_orders as (
    select distinct o.order_number
    from {{ ref('stg_younium__orders') }} o
    where exists (
      select 1 from {{ ref('quarantine') }} q
      where (q.source_table = 'younium_orders' and q.record_id = o.record_id)
         or (q.source_table = 'younium_accounts' and q.record_id = o.account_number)
         or (q.source_table = 'hubspot_deals' and q.record_id = o.hubspot_deal_id)
    ) or exists (
      select 1 from {{ ref('stg_younium__order_charges') }} charge
      join {{ ref('quarantine') }} q
        on q.source_table = 'younium_order_charges' and q.record_id = charge.record_id
      where charge.order_number = o.order_number and charge.version = o.version
    )
), keys as (
    select order_number from billing
    union select order_number from crm
), balances as (
    select k.order_number, b.version as billing_version, b.rate_to_chf,
        coalesce(b.arr_chf, 0)::decimal(38,2) as billing_arr_chf,
        coalesce(c.crm_arr_chf, 0)::decimal(38,2) as crm_arr_chf,
        coalesce(c.crm_deal_count, 0) as crm_deal_count,
        coalesce(e.has_won_deal, false) as has_won_deal,
        coalesce(e.has_unvalued_crm_contract, false) as has_unvalued_crm_contract,
        coalesce(e.has_value_mismatch, false) as has_value_mismatch,
        coalesce(e.has_timing_mismatch, false) as has_timing_mismatch,
        q.order_number is not null as is_quarantined,
        exists (select 1 from {{ ref('chk_r9_duplicate_push') }} r
                where r.record_id = k.order_number) as is_duplicate_push,
        exists (select 1 from {{ ref('chk_r2_billing_without_crm') }} r
                where r.record_id = k.order_number) as is_billing_only,
        coalesce(b.auto_renew and b.hubspot_deal_id is null
          and b.version > {{ rule('initial_order_version') }} and c.order_number is null
          and exists (
            select 1 from {{ ref('stg_younium__orders') }} history
            join {{ ref('stg_hubspot__deals') }} d on d.deal_id = history.hubspot_deal_id
            where history.order_number = k.order_number
              and history.status <> {{ rule_value('draft_order_status') }}
              and d.is_closed_won and d.contract_end <= b.month_end
          ), false) as is_billing_only_renewal
    from keys k
    left join billing b using (order_number)
    left join crm c using (order_number)
    left join evidence e using (order_number)
    left join quarantined_orders q using (order_number)
), version_changes as (
    select *, lag(recurring_mrr) over (partition by order_number order by version) as previous_mrr
    from {{ ref('int_order_financials') }} where status <> {{ rule_value('draft_order_status') }}
), changes as (
    select o.order_number,
        cast(round(sum((v.recurring_mrr - v.previous_mrr) * {{ rule('months_per_year') }}
            * o.rate_to_chf), 2) as decimal(38,2)) as billing_change_chf
    from balances o
    join version_changes v on v.order_number = o.order_number and v.version <= o.billing_version
      and v.effective_start <= last_day({{ as_of_date() }})
    join {{ ref('chk_r10_billing_changes') }} r on r.record_id = v.record_id
    where not o.is_quarantined and not o.is_duplicate_push
      and not o.is_billing_only and not o.is_billing_only_renewal
    group by o.order_number
)
select b.*, coalesce(c.billing_change_chf, 0)::decimal(38,2) as billing_change_chf,
    (b.billing_arr_chf - b.crm_arr_chf - coalesce(c.billing_change_chf, 0))::decimal(38,2)
        as remaining_chf,
    case when is_quarantined then 'quarantined'
         when is_duplicate_push then 'double_billed'
         when is_billing_only_renewal then 'renewed_in_billing_only'
         when is_billing_only then 'billed_not_in_crm'
         when has_unvalued_crm_contract and crm_deal_count = 0 then 'crm_arr_not_valued'
         when has_value_mismatch then 'value_mismatch'
         when has_timing_mismatch then 'timing'
         when crm_deal_count > 0 and billing_version is not null then 'within_tolerance'
         else 'unexplained' end as remaining_category
from balances b left join changes c using (order_number)
