select {{ finding('R7', 'order', 'o.order_number', 'o.owner_id', "'renewal window has no open renewal deal'",
  'struct_pack(effective_end := o.effective_end, auto_renew := o.auto_renew, recurring_mrr := o.recurring_mrr, currency := o.currency)',
  'case when o.auto_renew then 0 else abs(o.arr_chf) end',
  'case when o.auto_renew then ' ~ rule_value('auto_renew_severity') ~ ' else ' ~ sql_string(rule('check_catalog')['R7']['severity']) ~ ' end') }}
from {{ ref('int_order_financials') }} o
where is_current and status = {{ rule_value('active_order_status') }} and not has_open_renewal
  and date_diff('day', {{ as_of_date() }}, effective_end) between 0 and {{ rule('renewal_window_days') }}
