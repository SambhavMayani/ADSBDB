"""Programmatic object storage preparation; no work during import."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestration.storage import create_client


def main():
    client = create_client()
    import os

    existing = {b['Name'] for b in client.list_buckets()['Buckets']}
    for zone in ('LANDING', 'FORMATTED', 'TRUSTED'):
        bucket = os.getenv('ECOSENTINEL_' + zone + '_BUCKET', zone.lower() + '-zone')
        if bucket not in existing:
            client.create_bucket(Bucket=bucket)
        print('Storage ready:', bucket)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
