select {{ finding('A7', 'company', 'c.company_id', 'c.owner_id', "'duplicate company domain'",
  'struct_pack(domain := c.domain_clean, primary_id := c.primary_company_id, secondary_id := c.company_id)') }}
from {{ ref('int_company_context') }} c
where domain_clean is not null and duplicate_domain_count > 1 and company_id <> primary_company_id
