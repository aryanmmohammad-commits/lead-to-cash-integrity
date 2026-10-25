select last_day({{ as_of_date() }} - month_index * interval '1 month')::date as month_end
from range({{ rule('arr_months') }}) months(month_index)
