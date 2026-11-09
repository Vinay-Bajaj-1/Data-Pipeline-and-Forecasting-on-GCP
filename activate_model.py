"""Explicitly promote a saved candidate; retains the previous active artifacts."""
import argparse
import shutil
from datetime import datetime, timezone
from config import MODELS_DIR, OUTPUTS_DIR

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('version')
    args = parser.parse_args()
    versions = (MODELS_DIR / 'versions').resolve()
    candidate = (versions / args.version).resolve()
    if candidate.parent != versions:
        raise ValueError('Provide a version folder name only')
    pairs = [('xgboost_return_model.json', MODELS_DIR), ('metadata.json', MODELS_DIR),
             ('test_metrics.csv', OUTPUTS_DIR), ('test_predictions.parquet', OUTPUTS_DIR)]
    for name, _ in pairs:
        if not (candidate / name).is_file():
            raise FileNotFoundError(candidate / name)
    from pipeline.runtime import tracked_run
    with tracked_run('activate'):
        archive = MODELS_DIR / 'archive' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        archive.mkdir(parents=True)
        for name, destination in pairs:
            destination.mkdir(parents=True, exist_ok=True)
            if (destination / name).exists():
                shutil.copy2(destination / name, archive / name)
            shutil.copy2(candidate / name, destination / name)
        (MODELS_DIR / 'active_version.txt').write_text(args.version)
if __name__ == '__main__':
    main()
