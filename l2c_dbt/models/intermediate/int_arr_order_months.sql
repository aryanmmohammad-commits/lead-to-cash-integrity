-- Use the version effective in each month, including historical Cancelled/Expired
-- versions. The highest version today can be scheduled for a future activation.
with cancellations as (
    select order_number, min(cancellation_date) as order_cancellation_date
    from {{ ref('stg_younium__orders') }}
    where status <> {{ rule_value('draft_order_status') }}
    group by order_number
)
select o.*, m.month_end, c.order_cancellation_date,
    count(*) over (partition by o.order_number, m.month_end) as candidate_count,
    {{ fx_rate('o.currency', 'm.month_end') }} as month_rate_to_chf
from {{ ref('int_order_versions') }} o
join {{ ref('int_arr_month_ends') }} m
  on o.effective_start <= m.month_end and m.month_end < o.effective_end
left join cancellations c using (order_number)
where o.status <> {{ rule_value('draft_order_status') }}
  and (c.order_cancellation_date is null or m.month_end < c.order_cancellation_date)
