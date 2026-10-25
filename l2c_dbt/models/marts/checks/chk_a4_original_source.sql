select {{ finding('A4', 'contact', 'c.contact_id', 'c.owner_id', "'missing original source'",
  'struct_pack(original_source := c.original_source)') }}
from {{ ref('int_contact_context') }} c where original_source is null
