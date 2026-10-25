with ranked as (
    select *, max(version) filter (
        where status <> {{ sql_string(var('rules')['draft_order_status']) }}
    ) over (partition by order_number) as current_version,
    bool_or(version is null and status <> {{ sql_string(var('rules')['draft_order_status']) }})
      over (partition by order_number) as has_unknown_version
    from {{ ref('stg_younium__orders') }}
)
select o.*, a.company_id, a.match_method as account_match_method,
       coalesce(o.version = o.current_version
           and o.status <> {{ sql_string(var('rules')['draft_order_status']) }}, false) as is_current
from ranked o
left join {{ ref('int_account_match') }} a using (account_number)
where not coalesce(a.is_quarantined, false)
  and not has_unknown_version
  and not exists (
      select 1 from {{ ref('int_source_quarantine') }} q
      where q.source_table = 'younium_orders' and q.record_id = o.record_id
  )
  and not exists (
      select 1 from {{ ref('stg_younium__order_charges') }} c
      join {{ ref('int_source_quarantine') }} q
        on q.source_table = 'younium_order_charges' and q.record_id = c.record_id
      where c.order_number = o.order_number and c.version = o.version
  )
