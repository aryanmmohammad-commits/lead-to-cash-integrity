select {{ finding('A11', 'contact', 'c.contact_id', 'c.owner_id', "'contact has no company'",
  'struct_pack(company_id := c.company_id)') }}
from {{ ref('int_contact_context') }} c where not company_exists
