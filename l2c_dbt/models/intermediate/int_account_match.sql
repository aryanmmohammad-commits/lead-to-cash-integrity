with issues as (
    select record_id, string_agg(distinct reason, ';' order by reason) as reason
    from {{ ref('int_source_quarantine') }}
    where source_table = 'younium_accounts'
    group by record_id
), companies as (
    select c.* from {{ ref('stg_hubspot__companies') }} c
    where not exists (
        select 1 from {{ ref('int_source_quarantine') }} q
        where q.source_table = 'hubspot_companies' and q.record_id = c.record_id
    )
), explicit_candidates as (
    select a.account_number, count(c.company_id) as n, min(c.company_id) as company_id
    from {{ ref('stg_younium__accounts') }} a
    left join companies c on c.company_id = a.hubspot_company_id
    group by a.account_number
), domain_candidates as (
    select a.account_number, count(c.company_id) as n, min(c.company_id) as company_id
    from {{ ref('stg_younium__accounts') }} a
    left join companies c on c.domain_clean = a.domain_clean
      and not list_contains({{ string_list(var('rules')['generic_email_domains']) }}, a.domain_clean)
    group by a.account_number
), resolved as (
    select a.account_number, a.hubspot_company_id, a.domain_clean, a.domain__raw,
      case when i.reason is not null then null
           when e.n = 1 then e.company_id
           when e.n = 0 and d.n = 1 then d.company_id end as company_id,
      case when i.reason is not null then 'quarantined'
           when e.n = 1 then 'hubspot_company_id'
           when e.n > 1 then 'ambiguous'
           when d.n = 1 then 'domain'
           when d.n > 1 then 'ambiguous' else 'unmatched' end as match_method,
      case when i.reason is not null then i.reason
           when e.n > 1 then 'multiple_company_id_matches'
           when e.n = 0 and d.n > 1 then 'multiple_company_domain_matches' end as quarantine_reason,
      case when e.n > 0 then e.n else d.n end as candidate_count
    from {{ ref('stg_younium__accounts') }} a
    join explicit_candidates e using (account_number)
    join domain_candidates d using (account_number)
    left join issues i on i.record_id = a.record_id
)
select *, quarantine_reason is not null as is_quarantined from resolved
