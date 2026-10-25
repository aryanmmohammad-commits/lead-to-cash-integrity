select {{ finding('A13', 'deal', 'd.deal_id', 'd.owner_id', "'missing or unknown owner'",
  'struct_pack(owner_id := d.source_owner_id)') }}
from {{ ref('int_deal_context') }} d where owner_id = {{ rule_value('unassigned_owner_id') }}
union all
select {{ finding('A13', 'company', 'c.company_id', 'c.owner_id', "'missing or unknown owner'",
  'struct_pack(owner_id := c.source_owner_id)') }}
from {{ ref('int_company_context') }} c where owner_id = {{ rule_value('unassigned_owner_id') }}
