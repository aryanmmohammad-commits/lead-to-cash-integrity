select p.failed_checks[failure_index] as check_id, {{ sql_string(rule('check_catalog')['P']['severity']) }}::varchar as severity,
    'deal'::varchar as object_type, p.deal_id as record_id, p.owner_id,
    p.reasons[failure_index] as reason,
    cast(to_json(struct_pack(status := p.status, reasons := p.reasons,
         days_since_contract_start := p.days_since_contract_start)) as varchar) as details,
    null::decimal(38,2) as money_at_risk_chf
from {{ ref('push_readiness') }} p, range(1, len(p.failed_checks) + 1) failures(failure_index)
union all
select {{ finding('P', 'deal', 'p.deal_id', 'p.owner_id', rule_value('push_ready_status'),
  'struct_pack(status := p.status, reasons := p.reasons)') }}
from {{ ref('push_readiness') }} p where status = {{ rule_value('push_ready_status') }}
