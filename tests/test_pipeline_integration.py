"""Real isolated S3 + Chroma + real zone code. Embedding inference is deterministic here.

Start docker-compose.test.yml first. The fixed test endpoint is separate from
the user's port 9000. Every bucket belongs to this test and is removed afterwards.
"""

import json
from pathlib import Path
import uuid
import numpy as np
import pytest
import soundfile as sf

from orchestration import pipeline
from orchestration.reconcile import reconcile
from landing_zone.temporal_landing import ingest_local_data as ingest
from landing_zone.persistent_landing import process_to_persistent as persistent
from formatted_zone import format_images, format_audio, format_text
from trusted_zone import validate_images, validate_audio, validate_text, pipeline_common
from exploitation_zone.indexer import execute, load_config
from exploitation_zone.source import TrustedRepository
from exploitation_zone.vector_store import VectorStore
from tests.test_exploitation_phase_a import Encoders

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated_store(monkeypatch):
    import boto3
    from botocore.config import Config

    # Never inherit .env, production endpoint or production credentials.
    client = boto3.client(
        's3',
        endpoint_url='http://127.0.0.1:19000',
        aws_access_key_id='ecosentinel_test',
        aws_secret_access_key='only_for_isolated_tests',
        config=Config(connect_timeout=2, read_timeout=5, retries={'max_attempts': 0}),
    )
    client.list_buckets()  # Explicit -m integration requires a running test service.
    prefix = 'eco-it-' + uuid.uuid4().hex[:12]
    buckets = {zone: prefix + '-' + zone for zone in ('landing', 'formatted', 'trusted')}
    for bucket in buckets.values():
        client.create_bucket(Bucket=bucket)
    monkeypatch.setattr(ingest, 'BUCKET_NAME', buckets['landing'])
    monkeypatch.setattr(ingest, 'minio_client', client)
    monkeypatch.setattr(persistent, 'BUCKET_NAME', buckets['landing'])
    monkeypatch.setattr(persistent, 'minio_client', client)
    for module in (format_images, format_audio, format_text):
        monkeypatch.setattr(module, 'LANDING_BUCKET', buckets['landing'])
        monkeypatch.setattr(module, 'FORMATTED_BUCKET', buckets['formatted'])
    monkeypatch.setattr(format_audio, 'create_minio_client', lambda: client)
    monkeypatch.setattr(format_text, 'create_minio_client', lambda: client)
    for module in (validate_images, validate_audio, validate_text, pipeline_common):
        monkeypatch.setattr(module, 'FORMATTED_BUCKET', buckets['formatted'])
        monkeypatch.setattr(module, 'TRUSTED_BUCKET', buckets['trusted'])
    yield client, buckets
    for bucket in buckets.values():
        assert bucket.startswith(prefix + '-') and prefix.startswith('eco-it-')
        for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket):
            for obj in page.get('Contents', []):
                client.delete_object(Bucket=bucket, Key=obj['Key'])
        client.delete_bucket(Bucket=bucket)


def seed(root):
    from PIL import Image

    for kind in ('images', 'audio', 'text'):
        folder = root / kind / 'lynx_pardinus'
        folder.mkdir(parents=True)
        if kind == 'images':
            file = folder / 'sample.png'
            rng = np.random.default_rng(42)
            Image.fromarray(rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)).save(file)
        elif kind == 'audio':
            file = folder / 'sample.wav'
            sf.write(file, 0.1 * np.sin(np.arange(8000) * 0.1), 32000, subtype='PCM_16')
        else:
            file = folder / 'sample.html'
            file.write_text(
                '<p>The Iberian lynx lives in Mediterranean forests and hunts rabbits.</p>'
            )
        (folder / '_metadata.json').write_text(
            json.dumps(
                [
                    {
                        'local_filename': file.name,
                        'source_name': 'synthetic_fixture',
                        'species_id': 'lynx_pardinus',
                    }
                ]
            )
        )


@pytest.mark.e2e
def test_full_pipeline_real_storage_reconciliation_and_rerun(isolated_store, tmp_path, monkeypatch):
    client, buckets = isolated_store
    seed(tmp_path / 'raw')
    monkeypatch.setattr(ingest, 'RAW_DATASET_ROOT', tmp_path / 'raw')
    cfg = load_config()
    cfg['trusted_bucket'] = buckets['trusted']
    index = tmp_path / 'index'
    store = VectorStore(index)
    encoders = Encoders()
    repository = TrustedRepository(client, buckets['trusted'])
    av, ac, ah = pipeline_common.load_policy('trusted_audio_quality.yaml', 'audio')
    tv, tc, th = pipeline_common.load_policy('trusted_text_quality.yaml', 'text')
    iv, ic = validate_images.load_policy()
    callbacks = {
        'minio-connection': lambda: client.list_buckets(),
        'initialize-buckets': lambda: 0,
        'temporal-ingest': lambda: ingest.ingest_dataset(),
        'persistent-promote': lambda: persistent.process_temporal_objects(),
        'format-images': lambda: format_images.format_images(client),
        'format-audio': lambda: format_audio.process_audio(decoder='soundfile'),
        'format-text': lambda: format_text.process_text(),
        'validate-images': lambda: validate_images.run(client, ic, iv, report=False),
        'validate-audio': lambda: validate_audio.run(client, ac, av, ah, report=False),
        'validate-text': lambda: validate_text.run(client, tc, tv, th, report=False),
        'reconcile': lambda: reconcile(repository, index, cfg),
    }
    for space in cfg['collections']:
        callbacks['index-' + space] = lambda space=space: execute(
            cfg, repository, vector_store=store, encoders=encoders, spaces=(space,)
        )
    summaries = []

    def runner(argv, root, log):
        name = next(step.name for step in steps if step.argv() == list(argv))
        result = callbacks[name]()
        summaries.append((name, result))
        log.write_text(json.dumps(result, default=str))
        return (
            int(bool(result.get('errors') or result.get('problems')))
            if isinstance(result, dict)
            else int(result or 0)
        )

    steps = pipeline.build_plan()
    # Validate actual entry points using the repository, while logs stay isolated.
    root = Path(__file__).resolve().parents[1]
    code, report = pipeline.run_pipeline(
        steps, root=root, report_dir=tmp_path / 'reports', runner=runner
    )
    assert code == 0
    assert json.loads(report.read_text())['status'] == 'completed'
    first = reconcile(repository, index, cfg)
    assert first['trusted_assets'] == 3 and first['total_vectors'] == 7 and not first['problems']
    sums = encoders.calls.copy()
    code, report = pipeline.run_pipeline(
        steps, root=root, report_dir=tmp_path / 'reports', runner=runner
    )
    assert code == 0 and encoders.calls == sums
    assert reconcile(repository, index, cfg) == first
    # Original raw remains present, including transient copies under the safe default.
    landing = [
        obj['Key']
        for page in client.get_paginator('list_objects_v2').paginate(Bucket=buckets['landing'])
        for obj in page.get('Contents', [])
    ]
    assert len([key for key in landing if key.startswith('persistent_landing/')]) == 3
    assert len([key for key in landing if key.startswith('temporal_landing/')]) == 3
