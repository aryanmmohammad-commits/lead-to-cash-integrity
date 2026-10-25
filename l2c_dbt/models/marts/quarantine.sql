select * from {{ ref('int_source_quarantine') }}
union
select 'younium_accounts' as source_table, account_number as record_id, 'domain' as "column",
       domain__raw as raw_value, 'ambiguous_domain' as reason
from {{ ref('int_account_match') }} where quarantine_reason = 'ambiguous'
union
select 'hubspot_deals' as source_table, deal_id as record_id, 'deal_id' as "column",
       deal_id__raw as raw_value, 'ambiguous' as reason
from {{ ref('int_deal_order_match') }} where quarantine_reason = 'ambiguous'
union
select 'younium_orders', record_id, 'version', version__raw, 'ambiguous'
from {{ ref('int_arr_order_months') }} where candidate_count > 1
union
select 'younium_orders', record_id, 'currency', currency__raw, 'no_fx_rate'
from {{ ref('int_arr_order_months') }} where month_rate_to_chf is null
union
select 'hubspot_deals', record_id, 'currency', currency__raw, 'no_fx_rate'
from {{ ref('int_arr_crm_months') }} where month_rate_to_chf is null
