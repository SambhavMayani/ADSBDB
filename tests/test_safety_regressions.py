"""Failure and recovery tests protect accepted data and the original index."""

import importlib
import sqlite3
import sys
import time
from collections import Counter
import pytest
from botocore.exceptions import ClientError
from orchestration import pipeline
from orchestration.audit import inventory, snapshot
from trusted_zone.pipeline_common import publish
from tests.test_trusted_images import (
    FakeS3,
    upload_formatted,
    make_jpeg,
    run as run_images,
    load_policy,
)
from tests.test_exploitation_phase_a import Collection, Repo, Store, Encoders, CONFIG
from exploitation_zone.indexer import execute
from exploitation_zone.vector_store import VectorStore


@pytest.mark.parametrize('code', ['403', '500', '503'])
def test_transient_image_read_never_deletes_accepted_object(code):
    client = FakeS3()
    key = upload_formatted(client, 'bubo_bubo', 'a', make_jpeg())
    cfg = load_policy()[1]
    run_images(client, cfg, '1', report=False)
    original = dict(client.objects[('trusted-zone', key)])
    get = client.get_object

    def fail_source(*, Bucket, Key):
        if Bucket == 'formatted-zone':
            raise ClientError({'Error': {'Code': code}}, 'GetObject')
        return get(Bucket=Bucket, Key=Key)

    client.get_object = fail_source
    result = run_images(client, cfg, '1', report=False)
    assert result['errors'] == 1 and result['error'] == 1
    assert client.objects[('trusted-zone', key)] == original


def test_quality_policy_change_proposes_retirement_without_data_loss():
    client = FakeS3()
    key = upload_formatted(client, 'bubo_bubo', 'a', make_jpeg())
    cfg = load_policy()[1]
    run_images(client, cfg, '1', report=False)
    result = run_images(client, dict(cfg, min_width=1000), '2', report=False)
    assert result['retirement_candidates'] == 1
    assert ('trusted-zone', key) in client.objects


@pytest.mark.parametrize('status', ['rejected', 'error'])
def test_audio_text_status_changes_preserve_history(status):
    from tests.test_trusted_audio_text import FakeS3 as S3

    client = S3()
    key = 'text/bubo_bubo/a.txt'
    client.put_object(
        Bucket='trusted-zone',
        Key=key,
        Body=b'accepted',
        ContentLength=8,
        ContentType='text/plain',
        Metadata={},
    )
    publish(
        client,
        key=key,
        modality='text',
        data=None,
        metadata={},
        source_sha=None,
        policy_version='2',
        policy_sha='p',
        status=status,
        manifest={'content_fingerprint': status, 'status': status},
        dry_run=False,
        stats=Counter(),
    )
    assert client.buckets['trusted-zone'][key][0] == b'accepted'


@pytest.mark.parametrize('modality', ['images', 'text', 'audio'])
def test_invalid_trusted_lineage_never_indexes(modality):
    ext = {'images': 'jpg', 'text': 'txt', 'audio': 'flac'}[modality]

    class BadRepo(Repo):
        def source_info(self, key):
            info = super().source_info(key)
            info['meta']['species_id'] = 'different'
            return info

    store = Store()
    result = execute(
        CONFIG,
        BadRepo({f'{modality}/bubo_bubo/a.{ext}': b'x'}),
        modality=modality,
        vector_store=store,
        encoders=Encoders(),
    )
    assert result['errors'] == 1 and not store.collections


def test_upsert_failure_preserves_prior_segments():
    col = Collection()
    col.rows['old'] = {'metadata': {'asset_id': 'asset'}, 'embedding': [1], 'document': 'old'}

    def fail(**kwargs):
        raise OSError('disk full')

    col.upsert = fail
    with pytest.raises(OSError):
        VectorStore.replace_asset(
            col,
            'asset',
            [{'id': 'new', 'vector': [1], 'metadata': {'asset_id': 'asset'}, 'document': 'new'}],
        )
    assert 'old' in col.rows


def test_recovery_after_partial_vector_publication():
    col = Collection()
    records = [
        {
            'id': str(i),
            'vector': [1],
            'metadata': {
                'asset_id': 'a',
                'source_sha256': 's',
                'policy_sha256': 'p',
                'expected_parts': 60,
                'part': i,
            },
            'document': 'x',
        }
        for i in range(60)
    ]
    actual = col.upsert
    calls = 0

    def flaky(**kw):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('interrupted batch')
        return actual(**kw)

    col.upsert = flaky
    with pytest.raises(OSError):
        VectorStore.replace_asset(col, 'a', records)
    assert not VectorStore.is_complete(col, 'a', 's', 'p')
    col.upsert = actual
    VectorStore.replace_asset(col, 'a', records)
    assert VectorStore.is_complete(col, 'a', 's', 'p') and len(col.rows) == 60


def test_changing_report_dir_cannot_bypass_writer_lock(tmp_path):
    (tmp_path / 'demo.py').write_text('')
    folder = tmp_path / 'reports/orchestration'
    folder.mkdir(parents=True)
    with pipeline._exclusive_run_lock(folder):
        with pytest.raises(RuntimeError):
            pipeline.run_pipeline(
                [pipeline.Step('storage', 'demo', 'demo.py')],
                root=tmp_path,
                report_dir=tmp_path / 'different',
                runner=lambda *a: 0,
            )


def test_real_process_timeout_reaps_child(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOSENTINEL_STEP_TIMEOUT', '0.2')
    script = tmp_path / 'slow.py'
    script.write_text('import time\ntime.sleep(20)\n')
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        pipeline._run_process([sys.executable, str(script)], tmp_path, tmp_path / 'out.log')
    assert time.monotonic() - start < 10


def test_child_unicode_is_lossless_on_windows(tmp_path):
    script = tmp_path / 'unicode.py'
    script.write_text("print('Lince ibérico · año 🦉')\n", encoding='utf-8')
    log = tmp_path / 'out.log'
    assert pipeline._run_process([sys.executable, str(script)], tmp_path, log) == 0
    assert 'Lince ibérico · año 🦉' in log.read_text(encoding='utf-8')


def test_storage_import_is_lazy(monkeypatch):
    from orchestration import storage

    def fail():
        pytest.fail('Import connected to S3')

    monkeypatch.setattr(storage, 'create_client', fail)
    importlib.reload(
        importlib.import_module('landing_zone.persistent_landing.process_to_persistent')
    )
    importlib.reload(importlib.import_module('landing_zone.temporal_landing.ingest_local_data'))


def fake_chroma(path):
    path.mkdir()
    with sqlite3.connect(path / 'chroma.sqlite3') as db:
        db.executescript(
            'CREATE TABLE collections(id TEXT,name TEXT); CREATE TABLE segments(id TEXT,collection TEXT); CREATE TABLE embeddings(id TEXT,segment_id TEXT); INSERT INTO collections VALUES("c","images"); INSERT INTO segments VALUES("s","c"); INSERT INTO embeddings VALUES("e","s");'
        )
    (path / 'hnsw.bin').write_bytes(b'index')


def test_snapshot_is_exact_and_source_unchanged(tmp_path):
    source, target = tmp_path / 'original', tmp_path / 'snapshot'
    fake_chroma(source)
    before = inventory(source)
    result = snapshot(source, target)
    assert result['counts'] == {'images': 1}
    assert before == inventory(source) == inventory(target)
    with pytest.raises(FileExistsError):
        snapshot(source, target)


def test_snapshot_rejects_nested_destination(tmp_path):
    source = tmp_path / 'original'
    fake_chroma(source)
    with pytest.raises(ValueError):
        snapshot(source, source / 'backup')


def test_corrupt_acquisition_metadata_preserved(tmp_path):
    from landing_zone.data_acquisition.download_species_texts import load_metadata

    path = tmp_path / '_metadata.json'
    path.write_text('{broken')
    with pytest.raises(ValueError):
        load_metadata(path, tmp_path)
    assert path.read_text() == '{broken'
