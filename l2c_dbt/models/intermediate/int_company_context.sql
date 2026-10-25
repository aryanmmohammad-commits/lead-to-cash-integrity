with evidence as (
    select companies.company_id,
      bool_or(d.is_closed_won) as has_closed_won,
      bool_or(d.is_open) as has_open_deal,
      bool_or(d.is_open and d.motion = {{ rule_value('renewal_deal_motion') }}) as has_open_renewal
    from {{ ref('stg_hubspot__deals') }} d,
         unnest(d.company_ids) companies(company_id)
    group by companies.company_id
)
select c.* exclude(owner_id), c.owner_id as source_owner_id,
    {{ resolved_owner('c.owner_id') }} as owner_id,
    coalesce(e.has_closed_won, false) as has_closed_won,
    coalesce(e.has_open_deal, false) as has_open_deal,
    coalesce(e.has_open_renewal, false) as has_open_renewal,
    case when e.has_closed_won then {{ rule_value('customer_lifecycle_stage') }}
         when e.has_open_deal then {{ rule_value('opportunity_lifecycle_stage') }}
         else {{ rule_value('lead_lifecycle_stage') }} end as evidence_lifecycle,
    case {% for territory, countries in rule('territory_by_country').items() %}
      when list_contains({{ string_list(countries) }}, c.country) then {{ sql_string(territory) }}
      {% endfor %} else {{ rule_value('default_territory') }} end as proposed_territory,
    count(*) over (partition by c.domain_clean) as duplicate_domain_count,
    first_value(c.company_id) over (partition by c.domain_clean
      order by c.created_at nulls last, c.company_id) as primary_company_id
from {{ ref('stg_hubspot__companies') }} c left join evidence e using (company_id)
