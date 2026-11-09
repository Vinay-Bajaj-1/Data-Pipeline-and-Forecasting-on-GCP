import json
import os
import traceback
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from uuid import uuid4
from config import BASE_DIR

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def tracked_run(mode):
    directory = BASE_DIR / 'logs'
    directory.mkdir(exist_ok=True)
    lock = directory / 'pipeline.lock'
    # Exclusive creation also protects a shared staging table from concurrent runs.
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    run_id = uuid4().hex
    record = {'run_id': run_id, 'mode': mode, 'status': 'running', 'started_at': now(), 'pid': os.getpid()}
    path = directory / f'{run_id}.json'
    try:
        os.write(descriptor, json.dumps(record).encode())
        path.write_text(json.dumps(record, indent=2))
        with (directory / f'{run_id}.log').open('w', encoding='utf-8') as output:
            with redirect_stdout(output), redirect_stderr(output):
                try:
                    yield record
                except BaseException as error:
                    record.update(status='failed', error=str(error))
                    traceback.print_exc()
                    raise
                else:
                    record['status'] = 'success'
    finally:
        record['finished_at'] = now()
        record['duration_seconds'] = (datetime.fromisoformat(record['finished_at']) - datetime.fromisoformat(record['started_at'])).total_seconds()
        path.write_text(json.dumps(record, indent=2, default=str))
        temporary = directory / 'latest.tmp'
        temporary.write_text(json.dumps(record, indent=2, default=str))
        os.replace(temporary, directory / 'latest.json')
        os.close(descriptor)
        lock.unlink()
        print(f"{record['status']}: {run_id}; log: {directory / (run_id + '.log')}")
