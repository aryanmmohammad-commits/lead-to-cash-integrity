select {{ finding('R11', 'account', 'a.account_number',
  'coalesce(c.owner_id, ' ~ rule_value('unassigned_owner_id') ~ ')', "'cancelled in billing, still customer in CRM'",
  'struct_pack(company_id := a.company_id, account_number := a.account_number)') }}
from {{ ref('int_account_match') }} a
left join {{ ref('int_company_context') }} c on c.company_id = a.company_id
where not a.is_quarantined
  and exists (select 1 from {{ ref('int_order_financials') }} cancelled
              where cancelled.account_number = a.account_number
                and cancelled.status = {{ rule_value('cancelled_order_status') }})
  and not exists (select 1 from {{ ref('int_order_financials') }} active
                  where active.account_number = a.account_number
                    and active.status = {{ rule_value('active_order_status') }}
                    and active.effective_start <= {{ as_of_date() }} and {{ as_of_date() }} < active.effective_end
                    and (active.cancellation_date is null or active.cancellation_date > {{ as_of_date() }}))
  and exists (select 1 from {{ ref('int_contact_context') }} contact
              where contact.company_id = a.company_id
                and contact.lifecycle_stage = {{ rule_value('customer_lifecycle_stage') }})
