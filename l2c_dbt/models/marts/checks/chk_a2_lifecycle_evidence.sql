select {{ finding('A2', 'contact', 'c.contact_id', 'c.owner_id', "'lifecycle contradicts deal evidence'",
  'struct_pack(current_value := c.lifecycle_stage, proposed_value := c.evidence_lifecycle)') }}
from {{ ref('int_contact_context') }} c
where list_contains({{ string_list(rule('lifecycle_order')) }}, lifecycle_stage)
  and ((lifecycle_stage = {{ rule_value('customer_lifecycle_stage') }} and not has_closed_won)
       or (list_contains({{ string_list(rule('pre_customer_lifecycle_stages')) }}, lifecycle_stage)
           and has_closed_won))
