select {{ finding('A10', 'contact', 'c.contact_id', 'c.owner_id', "'duplicate contact email'",
  'struct_pack(email := c.email, primary_id := c.primary_contact_id, secondary_id := c.contact_id)') }}
from {{ ref('int_contact_context') }} c
where email is not null and duplicate_email_count > 1 and contact_id <> primary_contact_id
