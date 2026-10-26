with deals as (
    select d.* from {{ ref('stg_hubspot__deals') }} d
    where not exists (
        select 1 from {{ ref('int_source_quarantine') }} q
        where q.source_table = 'hubspot_deals' and q.record_id = d.record_id
    )
      and not exists (
          select 1 from {{ ref('int_arr_crm_months') }} unpriced
          where unpriced.deal_id = d.deal_id and unpriced.month_rate_to_chf is null
      )
), candidates as (
    select d.deal_id, o.order_number, o.version, o.record_id as order_record_id,
           o.effective_start, o.effective_end, o.currency as billing_currency,
           row_number() over (partition by d.deal_id order by o.order_number, o.version) as rank
    from deals d
    join {{ ref('int_order_versions') }} o on o.hubspot_deal_id = d.deal_id
    where o.status <> {{ sql_string(var('rules')['draft_order_status']) }}
      and not exists (
          select 1 from {{ ref('int_arr_order_months') }} ambiguous
          where ambiguous.record_id = o.record_id
            and (ambiguous.candidate_count > 1 or ambiguous.month_rate_to_chf is null)
      )
      and ((d.motion = {{ sql_string(var('rules')['new_deal_motion']) }}
            and o.version = {{ var('rules')['initial_order_version'] }})
           or list_contains({{ string_list(var('rules')['change_deal_motions']) }}, d.motion))
), counts as (
    select deal_id, count(*) as n, count(distinct order_number) as order_count,
           list(order_number order by order_number) as order_numbers
    from candidates group by deal_id
), resolution as (
    select d.*, coalesce(c.n, 0) as candidate_count,
      coalesce(c.n = 1 or (d.motion = {{ sql_string(var('rules')['new_deal_motion']) }}
                          and c.n = c.order_count), false) as may_match,
      case when c.n > 1 and not (d.motion = {{ sql_string(var('rules')['new_deal_motion']) }}
                                and c.n = c.order_count) then 'multiple_deal_order_matches' end as quarantine_reason,
      case when d.motion = {{ sql_string(var('rules')['new_deal_motion']) }} and c.n = c.order_count
           then list_slice(c.order_numbers, 2, c.n) else []::varchar[] end as duplicate_order_numbers
    from deals d left join counts c using (deal_id)
)
select r.*,
    case when may_match then c.order_number end as order_number,
    case when may_match then c.version end as version,
    case when may_match then c.order_record_id end as order_record_id,
    case when may_match then c.effective_start end as order_effective_start,
    case when may_match then c.effective_end end as order_effective_end,
    case when may_match then c.billing_currency end as billing_currency,
    case when r.quarantine_reason is not null then 'ambiguous'
         when not may_match then 'unmatched'
         when len(duplicate_order_numbers) > 0 then 'duplicate_push'
         else 'hubspot_deal_id' end as match_method,
    may_match as is_matched,
    exists (
        select 1 from {{ ref('stg_younium__orders') }} draft
        where draft.hubspot_deal_id = r.deal_id
          and draft.status = {{ sql_string(var('rules')['draft_order_status']) }}
    ) as has_draft_order
from resolution r left join candidates c on r.deal_id = c.deal_id and c.rank = 1
