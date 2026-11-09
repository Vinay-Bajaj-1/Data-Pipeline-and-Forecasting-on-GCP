SELECT
    symbol,
    COUNT(*) AS total_rows,
    COUNT(*) - COUNT(DISTINCT trade_date) AS duplicate_dates,

    COUNTIF(
        symbol IS NULL OR TRIM(symbol) = ''
        OR trade_date IS NULL
        OR open IS NULL
        OR high IS NULL
        OR low IS NULL
        OR close IS NULL
        OR adjusted_close IS NULL
        OR volume IS NULL
        OR ingested_at IS NULL
        OR batch_id IS NULL
    ) AS missing_values,

    COUNTIF(
        batch_id IS NULL OR batch_id != @batch_id
    ) AS wrong_batch,

    COUNTIF(
        EXISTS (
            SELECT 1
            FROM UNNEST([
                open, high, low, close, adjusted_close
            ]) AS price
            WHERE price <= 0
                OR IS_NAN(price)
                OR IS_INF(price)
        )
    ) AS invalid_prices,

    COUNTIF(
        low > high
        OR open < low OR open > high
        OR close < low OR close > high
    ) AS invalid_ranges,

    COUNTIF(volume < 0) AS negative_volume,

    COUNTIF(
        trade_date >= CURRENT_DATE('Asia/Kolkata')
    ) AS invalid_dates

FROM `{table_id}`
GROUP BY symbol