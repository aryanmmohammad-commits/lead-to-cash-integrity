with parsing as (
    {{ source_quarantine() }}
), generic_domains as (
    select 'younium_accounts' as source_table, a.record_id, 'domain' as "column",
           a.domain__raw as raw_value, 'generic_email_domain' as reason
    from {{ ref('stg_younium__accounts') }} a
    where list_contains({{ string_list(var('rules')['generic_email_domains']) }}, a.domain_clean)
      and not exists (
          select 1 from {{ ref('stg_hubspot__companies') }} c
          where c.company_id = a.hubspot_company_id and c.is_parse_valid
      )
)
select distinct * from parsing
union
select * from generic_domains
