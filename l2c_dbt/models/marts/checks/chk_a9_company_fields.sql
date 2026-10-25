select {{ finding('A9', 'company', 'c.company_id', 'c.owner_id', "'missing territory or tier'",
  'struct_pack(territory := c.territory, tier := c.tier, proposed_territory := c.proposed_territory)') }}
from {{ ref('int_company_context') }} c where territory is null or tier is null
