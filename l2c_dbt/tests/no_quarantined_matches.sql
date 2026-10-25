select account_number as record_id from {{ ref('int_account_match') }}
where is_quarantined and company_id is not null
union all
select deal_id as record_id from {{ ref('int_deal_order_match') }}
where quarantine_reason is not null and (is_matched or order_number is not null)
