select {{ finding('R8', 'invoice', 'i.invoice_number', rule_value('finance_owner_id'), "'uncredited invoice after cancellation'",
  'struct_pack(order_number := i.order_number, cancellation_date := o.cancellation_date, service_period_start := i.service_period_start, service_period_end := i.service_period_end, amount := i.amount, currency := i.currency)',
  'abs(i.amount * ' ~ fx_rate('i.currency', 'coalesce(i.posted_date, ' ~ as_of_date() ~ ')') ~ ')') }}
from {{ ref('stg_younium__invoices') }} i
join {{ ref('int_order_financials') }} o on o.order_number = i.order_number and o.is_current
where i.status = {{ rule_value('posted_invoice_status') }} and not i.is_credit
  and i.service_period_start > o.cancellation_date and {{ trusted('younium_invoices', 'i') }}
  and not exists (
      select 1 from {{ ref('stg_younium__invoices') }} credit
      where credit.order_number = i.order_number and credit.is_credit
        and credit.service_period_start = i.service_period_start
        and credit.service_period_end = i.service_period_end
        and {{ trusted('younium_invoices', 'credit') }}
  )
