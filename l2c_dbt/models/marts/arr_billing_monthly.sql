select o.month_end, o.order_number, o.version, o.account_number, o.company_id,
    o.hubspot_deal_id, o.auto_renew, o.currency,
    coalesce(sum(c.mrr), 0) as recurring_mrr,
    o.month_rate_to_chf as rate_to_chf,
    cast(round(coalesce(sum(c.mrr), 0) * {{ rule('months_per_year') }}
        * o.month_rate_to_chf, 2) as decimal(38, 2)) as arr_chf
from {{ ref('int_arr_order_months') }} o
left join {{ ref('stg_younium__order_charges') }} c
  on c.order_number = o.order_number and c.version = o.version
  and c.charge_type = {{ rule_value('recurring_charge_type') }}
  and c.effective_start <= o.month_end and o.month_end < c.effective_end
  and {{ trusted('younium_order_charges', 'c') }}
where o.candidate_count = 1 and o.month_rate_to_chf is not null
  and {{ trusted('younium_orders', 'o') }}
group by o.month_end, o.order_number, o.version, o.account_number, o.company_id,
    o.hubspot_deal_id, o.auto_renew, o.currency, o.month_rate_to_chf
