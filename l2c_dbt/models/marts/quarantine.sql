select * from {{ ref('int_source_quarantine') }}
union
select 'younium_accounts' as source_table, account_number as record_id, 'domain' as "column",
       domain__raw as raw_value, 'ambiguous_domain' as reason
from {{ ref('int_account_match') }} where quarantine_reason = 'ambiguous'
union
select 'hubspot_deals' as source_table, deal_id as record_id, 'deal_id' as "column",
       deal_id__raw as raw_value, 'ambiguous' as reason
from {{ ref('int_deal_order_match') }} where quarantine_reason = 'ambiguous'
