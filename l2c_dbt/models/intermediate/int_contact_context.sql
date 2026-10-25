select c.* exclude(owner_id), c.owner_id as source_owner_id,
    coalesce(company.owner_id, {{ rule_value('unassigned_owner_id') }}) as owner_id,
    company.company_id is not null as company_exists,
    coalesce(company.has_closed_won, false) as has_closed_won,
    coalesce(company.has_open_deal, false) as has_open_deal,
    coalesce(company.evidence_lifecycle, {{ rule_value('lead_lifecycle_stage') }}) as evidence_lifecycle,
    count(*) over (partition by c.email) as duplicate_email_count,
    first_value(c.contact_id) over (partition by c.email
      order by c.created_at nulls last, c.contact_id) as primary_contact_id
from {{ ref('stg_hubspot__contacts') }} c
left join {{ ref('int_company_context') }} company using (company_id)
