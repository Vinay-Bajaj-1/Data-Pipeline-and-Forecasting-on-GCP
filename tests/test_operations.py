import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import pipeline.runtime as runtime
from pipeline.warehouse import BigQueryWarehouse
import run_pipeline

class OperationsTests(unittest.TestCase):
    def test_lock_and_success_log(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, 'BASE_DIR', Path(directory)):
            with runtime.tracked_run('test'):
                with self.assertRaises(FileExistsError):
                    with runtime.tracked_run('overlap'):
                        pass
            record = json.loads((Path(directory) / 'logs/latest.json').read_text())
            self.assertEqual(record['status'], 'success')
            self.assertFalse((Path(directory) / 'logs/pipeline.lock').exists())

    def test_failure_recorded_and_propagated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, 'BASE_DIR', Path(directory)):
            with self.assertRaisesRegex(ValueError, 'invalid batch'):
                with runtime.tracked_run('test'):
                    raise ValueError('invalid batch')
            record = json.loads((Path(directory) / 'logs/latest.json').read_text())
            self.assertEqual(record['status'], 'failed')
            self.assertEqual(record['error'], 'invalid batch')

    def test_invalid_staging_blocks_merge(self):
        with patch.object(run_pipeline, 'BigQueryWarehouse') as factory, patch.object(run_pipeline, 'DataIngestion') as ingest, patch.object(run_pipeline, 'StockModel'), patch.object(run_pipeline.storage, 'Client'):
            warehouse = factory.return_value
            ingest.return_value.download_all.return_value = 10
            ingest.return_value.upload_to_gcs.return_value = ['gs://test/batch.parquet']
            warehouse.load_staging_from_gcs.side_effect = ValueError('invalid staging')
            with self.assertRaisesRegex(ValueError, 'invalid staging'):
                run_pipeline.run_daily_pipeline({})
            warehouse.merge_staging_to_main.assert_not_called()
            warehouse.refresh_stock_features.assert_not_called()

    def test_unexpected_stock_rejected(self):
        client = MagicMock()
        row = MagicMock()
        row.symbol = 'UNEXPECTED'
        row.total_rows = 1
        row.__getitem__.return_value = 0
        client.query.return_value.result.return_value = [row]
        with self.assertRaisesRegex(ValueError, 'Unexpected symbols'):
            BigQueryWarehouse(client).validate_staging('batch', 1)

if __name__ == '__main__':
    unittest.main()
