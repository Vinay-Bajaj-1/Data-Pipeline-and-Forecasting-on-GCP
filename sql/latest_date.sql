select symbol, max(trade_date) as last_trade_date
from `{project_id}.finflow.raw_stock_prices`
group by symbol