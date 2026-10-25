select {{ finding('A8', 'deal', 'd.deal_id', 'd.owner_id', "'stale open deal'",
  'struct_pack(close_date := d.close_date, days_overdue := date_diff(\'day\', d.close_date, ' ~ as_of_date() ~ '))') }}
from {{ ref('int_deal_context') }} d
where is_open and date_diff('day', close_date, {{ as_of_date() }}) > {{ rule('stale_open_deal_days') }}
