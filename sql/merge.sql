MERGE `{target_table}` AS target
    USING (
        SELECT *
        FROM `{staging_table}`
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY symbol, trade_date
            ORDER BY ingested_at DESC, batch_id DESC
        ) = 1
    ) AS source
    ON target.symbol = source.symbol
       AND target.trade_date = source.trade_date

    WHEN MATCHED
      AND source.ingested_at > target.ingested_at
    THEN UPDATE SET
        open = source.open,
        high = source.high,
        low = source.low,
        close = source.close,
        adjusted_close = source.adjusted_close,
        volume = source.volume,
        ingested_at = source.ingested_at,
        batch_id = source.batch_id

    WHEN NOT MATCHED THEN
    INSERT (
        symbol, trade_date,
        open, high, low, close, adjusted_close, volume,
        ingested_at, batch_id
    )
    VALUES (
        source.symbol, source.trade_date,
        source.open, source.high, source.low, source.close,
        source.adjusted_close, source.volume,
        source.ingested_at, source.batch_id
    );