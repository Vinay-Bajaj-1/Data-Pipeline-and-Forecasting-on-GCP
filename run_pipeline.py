import argparse
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
from google.cloud import storage

from config import SYMBOLS
from pipeline.runtime import tracked_run
from pipeline.ingestion import DataIngestion
from pipeline.warehouse import BigQueryWarehouse
from pipeline.model import StockModel


def run_training():
    warehouse = BigQueryWarehouse()
    model = StockModel()

    print("--- Starting Model Training Pipeline ---")
    df = warehouse.load_training_data()
    train, val, test, _ = model.build_features(df)
    model.train(train, val)
    test_results = model.evaluate_test(test)
    model.save_artifacts(test_results, train, val, test)
    print("--- Training Pipeline Completed Successfully ---")


def run_daily_pipeline(record=None):
    warehouse = BigQueryWarehouse()
    ingestion = DataIngestion()
    model = StockModel()

    print("--- Starting Daily Ingestion & Forecasting Pipeline ---")
    model.load_model()

    batch_id = uuid4().hex
    ingested_at = datetime.now(ZoneInfo("UTC"))
    if record is not None:
        record["batch_id"] = batch_id

    # 1. Query latest warehouse dates & download incremental data
    latest_dates = warehouse.query_latest_dates()
    expected_rows = ingestion.download_all(batch_id=batch_id, ingested_at=ingested_at, latest_dates=latest_dates)

    # 2. Upload parquet batches to GCS
    storage_client = storage.Client(project=warehouse.project_id)
    uploaded_uris = ingestion.upload_to_gcs(storage_client=storage_client, batch_id=batch_id)

    # 3. Load to BigQuery staging & merge into raw
    warehouse.load_staging_from_gcs(uris=uploaded_uris, batch_id=batch_id, expected_rows=expected_rows)
    affected = warehouse.merge_staging_to_main()
    if record is not None:
        record.update(downloaded_rows=expected_rows, uploaded_files=len(uploaded_uris), merged_rows=affected)

    # 4. Refresh BigQuery feature views
    warehouse.refresh_stock_features()

    # 5. Extract latest feature rows and predict
    df = warehouse.load_training_data()
    _, _, _, prediction_rows = model.build_features(df)
    model.generate_latest_forecasts(prediction_rows)

    print(f"--- Daily Pipeline Completed Successfully [Batch: {batch_id}] ---")


def main():
    parser = argparse.ArgumentParser(description="FinFlow GCP Pipeline")
    parser.add_argument("--mode", choices=["train", "daily"], required=True)
    args = parser.parse_args()

    with tracked_run(args.mode) as record:
        if args.mode == "train":
            run_training()
        else:
            run_daily_pipeline(record)


if __name__ == "__main__":
    main()
