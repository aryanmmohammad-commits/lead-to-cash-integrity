-- Independent totals: unexplained is an entity-level classification, not a
-- balancing plug. A dropped/duplicated ledger contribution must fail this test.
with totals as (
    select
      coalesce((select sum(arr_chf) from {{ ref('arr_billing_monthly') }}
                where month_end = last_day({{ as_of_date() }})), 0) as billing_arr_chf,
      coalesce((select sum(arr_chf) from {{ ref('arr_crm_monthly') }}
                where month_end = last_day({{ as_of_date() }})), 0) as crm_arr_chf,
      coalesce((select sum(amount_chf) from {{ ref('arr_bridge') }}), 0) as bridge_chf
)
select * from totals where round(bridge_chf, 2) <> round(billing_arr_chf - crm_arr_chf, 2)
