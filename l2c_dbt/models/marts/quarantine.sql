select * from {{ ref('int_source_quarantine') }}
union
select 'younium_accounts' as source_table, a.account_number as record_id,
       case when a.quarantine_reason = 'multiple_company_id_matches'
            then 'hubspot_company_id' else 'domain' end as "column",
       case when a.quarantine_reason = 'multiple_company_id_matches'
            then s.hubspot_company_id__raw else s.domain__raw end as raw_value,
       a.quarantine_reason as reason
from {{ ref('int_account_match') }} a
join {{ ref('stg_younium__accounts') }} s using (account_number)
where a.match_method = 'ambiguous'
union
select 'hubspot_deals' as source_table, deal_id as record_id, 'deal_id' as "column",
       deal_id__raw as raw_value, quarantine_reason as reason
from {{ ref('int_deal_order_match') }} where quarantine_reason is not null
union
select 'younium_orders', record_id, 'version', version__raw, 'overlapping_order_versions'
from {{ ref('int_arr_order_months') }} where candidate_count > 1
union
select 'younium_orders', record_id, 'currency', currency__raw, 'no_fx_rate'
from {{ ref('int_arr_order_months') }} where month_rate_to_chf is null
union
select 'hubspot_deals', record_id, 'currency', currency__raw, 'no_fx_rate'
from {{ ref('int_arr_crm_months') }} where month_rate_to_chf is null
