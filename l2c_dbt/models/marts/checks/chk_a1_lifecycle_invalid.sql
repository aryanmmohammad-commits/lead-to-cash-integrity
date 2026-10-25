select {{ finding('A1', 'contact', 'c.contact_id', 'c.owner_id', "'invalid lifecycle stage'",
  'struct_pack(current_value := c.lifecycle_stage, proposed_value := c.evidence_lifecycle)') }}
from {{ ref('int_contact_context') }} c
where lifecycle_stage is null or not list_contains({{ string_list(rule('lifecycle_order')) }}, lifecycle_stage)
