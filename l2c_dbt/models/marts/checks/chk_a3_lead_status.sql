select {{ finding('A3', 'contact', 'c.contact_id', 'c.owner_id', "'lead status contradicts evidence'",
  'struct_pack(current_value := c.lead_status, lifecycle_stage := c.lifecycle_stage, has_open_deal := c.has_open_deal)') }}
from {{ ref('int_contact_context') }} c
where (lifecycle_stage = {{ rule_value('customer_lifecycle_stage') }}
       and list_contains({{ string_list(rule('customer_conflicting_lead_statuses')) }}, lead_status))
   or (lifecycle_stage is distinct from {{ rule_value('customer_lifecycle_stage') }}
       and has_open_deal and lead_status is distinct from {{ rule_value('open_deal_lead_status') }})
