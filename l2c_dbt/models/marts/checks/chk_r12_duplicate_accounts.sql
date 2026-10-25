with duplicates as (
    select a.*, count(*) over (partition by hubspot_company_id) as n,
      min(account_number) over (partition by hubspot_company_id) as primary_account
    from {{ ref('stg_younium__accounts') }} a
    where hubspot_company_id is not null and {{ trusted('younium_accounts', 'a') }}
)
select {{ finding('R12', 'account', 'a.account_number', rule_value('finance_owner_id'), "'multiple billing accounts reference one company'",
  'struct_pack(hubspot_company_id := a.hubspot_company_id, primary_account := a.primary_account, account_number := a.account_number)') }}
from duplicates a where n > 1 and account_number <> primary_account
