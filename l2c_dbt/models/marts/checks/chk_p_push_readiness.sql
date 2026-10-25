select reason as check_id, {{ sql_string(rule('check_catalog')['P']['severity']) }}::varchar as severity,
    'deal'::varchar as object_type, p.deal_id as record_id, p.owner_id,
    reason, cast(to_json(struct_pack(status := p.status, reasons := p.reasons)) as varchar) as details,
    null::decimal(38,2) as money_at_risk_chf
from {{ ref('push_readiness') }} p, unnest(p.reasons) failures(reason)
union all
select {{ finding('P', 'deal', 'p.deal_id', 'p.owner_id', rule_value('push_ready_status'),
  'struct_pack(status := p.status, reasons := p.reasons)') }}
from {{ ref('push_readiness') }} p where status = {{ rule_value('push_ready_status') }}
