"""Shared S3 configuration. Importing this module never opens a connection."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]


def create_client():
    import boto3
    from botocore.config import Config
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    access, secret = os.getenv('MINIO_ROOT_USER'), os.getenv('MINIO_ROOT_PASSWORD')
    if not access or not secret:
        raise RuntimeError('Set local MINIO_ROOT_USER and MINIO_ROOT_PASSWORD')
    endpoint = os.getenv('S3_ENDPOINT_URL', os.getenv('MINIO_ENDPOINT', 'http://localhost:9000'))
    if not endpoint.startswith(('http://', 'https://')):
        raise ValueError('S3 endpoint must be an HTTP(S) URL')
    return boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=access,
                        aws_secret_access_key=secret,
                        config=Config(connect_timeout=5, read_timeout=60,
                                      retries={'mode': 'standard', 'max_attempts': 3}))


class LazyClient:
    """Compatibility bridge for original Landing functions and test injection."""
    def __init__(self):
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            self._client = create_client()
        return getattr(self._client, name)
