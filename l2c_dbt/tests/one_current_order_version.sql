select order_number
from {{ ref('int_order_versions') }}
where is_current
group by order_number
having count(*) > 1
