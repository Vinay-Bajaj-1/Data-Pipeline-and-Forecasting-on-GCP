from pathlib import Path
import pandas as pd
from google.cloud import bigquery

from config import (
    LOCATION,
    MAIN_TABLE_ID,
    PROJECT_ID,
    SQL_DIR,
    SYMBOLS,
    TABLE_ID,
)


class BigQueryWarehouse:
    """Handles BigQuery staging, table validation, merge transformations, and feature updates."""

    def __init__(self, client: bigquery.Client = None):
        self.project_id = PROJECT_ID
        self.location = LOCATION
        self.client = client or bigquery.Client(project=self.project_id)

    def _read_sql(self, file_name: str) -> str:
        return (SQL_DIR / file_name).read_text(encoding="utf-8")

    def query_latest_dates(self) -> dict[str, any]:
        query_sql = self._read_sql("latest_date.sql").format(project_id=self.project_id)
        rows = self.client.query(query_sql, location=self.location).result()
        return {row.symbol: row.last_trade_date for row in rows}

    def load_staging_from_gcs(self, uris: list[str], batch_id: str, expected_rows: int):
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            schema=[
                bigquery.SchemaField("symbol", "STRING"),
                bigquery.SchemaField("trade_date", "DATE"),
                bigquery.SchemaField("open", "FLOAT"),
                bigquery.SchemaField("high", "FLOAT"),
                bigquery.SchemaField("low", "FLOAT"),
                bigquery.SchemaField("close", "FLOAT"),
                bigquery.SchemaField("adjusted_close", "FLOAT"),
                bigquery.SchemaField("volume", "INTEGER"),
                bigquery.SchemaField("ingested_at", "TIMESTAMP"),
                bigquery.SchemaField("batch_id", "STRING"),
            ],
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="trade_date",
            ),
            clustering_fields=["symbol"],
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )

        job = self.client.load_table_from_uri(
            uris,
            TABLE_ID,
            location=self.location,
            job_config=job_config,
        )
        job.result()
        print(f"Staging load job: {job.job_id}")
        print("BigQuery staging load complete.")
        self.validate_staging(batch_id=batch_id, expected_rows=expected_rows)

    def validate_staging(self, batch_id: str, expected_rows: int = None):
        expected_symbols = set(SYMBOLS)
        validation_sql = self._read_sql("validation.sql").format(table_id=TABLE_ID)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)
            ]
        )

        results = list(self.client.query(
            validation_sql,
            location=self.location,
            job_config=job_config,
        ).result())

        if not results:
            raise ValueError("Staging table is empty")

        actual_symbols = {row.symbol for row in results}
        errors = []

        missing = expected_symbols - actual_symbols
        if missing:
            errors.append(f"Missing symbols: {missing}")

        unexpected = actual_symbols - expected_symbols
        if unexpected:
            errors.append(f"Unexpected symbols: {unexpected}")
        total_rows = sum(row.total_rows for row in results)
        if expected_rows is not None and total_rows != expected_rows:
            errors.append(f"Expected {expected_rows:,} rows, found {total_rows:,}")

        checks = [
            "duplicate_dates", "missing_values", "wrong_batch",
            "invalid_prices", "invalid_ranges", "negative_volume", "invalid_dates",
        ]
        for row in results:
            for check in checks:
                if row[check] > 0:
                    errors.append(f"{row.symbol}: {check} = {row[check]}")

        if errors:
            raise ValueError("Staging validation failed:\n- " + "\n- ".join(errors))

        print(f"Staging validation passed: {len(actual_symbols)} stocks, {total_rows:,} rows")

    def merge_staging_to_main(self) -> int:
        merge_sql = self._read_sql("merge.sql").format(
            target_table=MAIN_TABLE_ID,
            staging_table=TABLE_ID,
        )
        merge_job = self.client.query(merge_sql, location=self.location)
        merge_job.result()
        print(f"Merge job: {merge_job.job_id}")
        affected = merge_job.num_dml_affected_rows
        print(f"Merge into raw_stock_prices complete. Rows affected: {affected}")
        return affected

    def refresh_stock_features(self):
        query = self._read_sql("build_stock_features.sql").format(project_id=self.project_id)
        job = self.client.query(query, location=self.location)
        job.result()
        print(f"Feature refresh job: {job.job_id}")
        print("Stock features refreshed successfully.")

    def load_training_data(self) -> pd.DataFrame:
        query = self._read_sql("build_training_data.sql").format(project_id=self.project_id)
        return self.client.query(query, location=self.location).to_dataframe(create_bqstorage_client=False)

    def query_stock_history(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        sql = f"""
        SELECT
            symbol,
            trade_date,
            open,
            high,
            low,
            close,
            adjusted_close,
            volume
        FROM `{MAIN_TABLE_ID}`
        WHERE symbol = @symbol
          AND trade_date BETWEEN @start_date AND @end_date
        ORDER BY trade_date ASC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("symbol", "STRING", symbol),
                bigquery.ScalarQueryParameter("start_date", "STRING", str(start_date)),
                bigquery.ScalarQueryParameter("end_date", "STRING", str(end_date)),
            ]
        )
        return self.client.query(sql, location=self.location, job_config=job_config).to_dataframe()

