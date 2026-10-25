with compared as (
    select d.*, o.arr_chf, abs(o.arr_chf - d.amount * d.rate_to_chf) as difference,
      round(abs(o.arr_chf - d.amount * d.rate_to_chf) / nullif(abs(d.amount * d.rate_to_chf), 0) * 100,
            {{ rule('amount_comparison_decimals') }}) as difference_pct
    from {{ ref('int_deal_context') }} d
    join {{ ref('int_order_financials') }} o on o.record_id = d.order_record_id
    where d.is_closed_won and d.motion = {{ rule_value('new_deal_motion') }}
      and d.is_trusted and d.amount is not null
)
select {{ finding('R3', 'deal', 'd.deal_id', 'd.owner_id', "'recurring value differs from deal ACV'",
  'struct_pack(deal_acv_chf := d.amount * d.rate_to_chf, billing_arr_chf := d.arr_chf, difference_pct := d.difference_pct)',
  'd.difference') }}
from compared d
where difference_pct > {{ rule('amount_tolerance_pct') }} or (amount = 0 and difference <> 0)
