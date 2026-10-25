with proposals as (
    select e.check_id, e.object_type, e.record_id,
      {{ proposal_property('hubspot_contacts', 'lifecycle_stage') }} as property,
      c.lifecycle_stage as current_value, c.evidence_lifecycle as proposed_value,
      coalesce(list_position({{ string_list(rule('lifecycle_order')) }}, c.evidence_lifecycle)
        < list_position({{ string_list(rule('lifecycle_order')) }}, c.lifecycle_stage), false) as requires_clear_first,
      e.reason
    from {{ ref('exceptions') }} e join {{ ref('int_contact_context') }} c on c.contact_id = e.record_id
    where e.check_id in ('A1','A2') and e.object_type = 'contact'
    union all
    select e.check_id, e.object_type, e.record_id,
      {{ proposal_property('hubspot_contacts', 'lead_status') }}, c.lead_status,
      case when c.lifecycle_stage = {{ rule_value('customer_lifecycle_stage') }}
           then {% if rule('customer_lead_status') is none %}null::varchar
                {% else %}{{ rule_value('customer_lead_status') }}{% endif %}
           else {{ rule_value('open_deal_lead_status') }} end,
      false, e.reason
    from {{ ref('exceptions') }} e join {{ ref('int_contact_context') }} c on c.contact_id = e.record_id
    where e.check_id = 'A3' and e.object_type = 'contact'
    union all
    select e.check_id, e.object_type, e.record_id,
      {{ proposal_property('hubspot_companies', 'territory') }}, c.territory, c.proposed_territory,
      false, e.reason
    from {{ ref('exceptions') }} e join {{ ref('int_company_context') }} c on c.company_id = e.record_id
    where e.check_id = 'A9' and e.object_type = 'company' and c.territory is null
    union all
    select e.check_id, e.object_type, e.record_id, {{ rule_value('merge_property') }},
      c.company_id, c.primary_company_id, false, e.reason
    from {{ ref('exceptions') }} e join {{ ref('int_company_context') }} c on c.company_id = e.record_id
    where e.check_id = 'A7' and e.object_type = 'company'
    union all
    select e.check_id, e.object_type, e.record_id, {{ rule_value('merge_property') }},
      c.contact_id, c.primary_contact_id, false, e.reason
    from {{ ref('exceptions') }} e join {{ ref('int_contact_context') }} c on c.contact_id = e.record_id
    where e.check_id = 'A10' and e.object_type = 'contact'
)
select md5(cast(to_json(struct_pack(check_id := check_id, object_type := object_type,
        record_id := record_id, property := property)) as varchar)) as proposal_id,
       check_id, object_type, record_id, property, current_value, proposed_value, requires_clear_first, reason
from proposals
