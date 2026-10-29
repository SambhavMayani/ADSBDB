"""Failure contracts for ingestion, formatting and reconciliation, without live storage."""

import hashlib
import io
import json
import sqlite3
from pathlib import Path

from botocore.exceptions import ClientError
import pytest

from exploitation_zone.source import TrustedRepository
from formatted_zone import format_images as formatted
from landing_zone.temporal_landing import ingest_local_data as landing
from orchestration.reconcile import reconcile
from tests.test_trusted_images import FakeS3, make_jpeg


class MemoryStorage(FakeS3):
    def __init__(self):
        super().__init__()
        self.buckets.add('landing-zone')
        self.streams = []
        self.uploads = []

    def get_object(self, *, Bucket, Key):
        self.head_object(Bucket=Bucket, Key=Key)
        body = io.BytesIO(self.objects[(Bucket, Key)]['body'])
        self.streams.append(body)
        return {'Body': body}

    def upload_file(self, *, Filename, Bucket, Key, ExtraArgs):
        self.uploads.append(Key)
        self.put_object(Bucket=Bucket, Key=Key, Body=Path(Filename).read_bytes(), **ExtraArgs)


@pytest.fixture
def raw_dataset(tmp_path, monkeypatch):
    root = tmp_path / 'raw'
    folder = root / 'text' / 'lynx_pardinus'
    folder.mkdir(parents=True)
    records = []
    for name in ('a.txt', 'b.txt'):
        (folder / name).write_text('Wildlife observations for ' + name, encoding='utf-8')
        records.append(
            {'local_filename': name, 'species_id': 'lynx_pardinus', 'source_name': 'fixture'}
        )
    (folder / '_metadata.json').write_text(json.dumps(records), encoding='utf-8')
    client = MemoryStorage()
    monkeypatch.setattr(landing, 'RAW_DATASET_ROOT', root)
    monkeypatch.setattr(landing, 'minio_client', client)
    files = sorted(landing.discover_local_files(), key=lambda f: f['path'].name)
    monkeypatch.setattr(landing, 'discover_local_files', lambda: files)
    return client, files


def test_landing_repeated_run_keeps_bytes_and_lineage(raw_dataset):
    client, files = raw_dataset
    assert landing.ingest_dataset() == 0
    original = dict(client.objects)
    assert len(client.uploads) == 2
    for info in files:
        key = landing.build_object_key(info)
        stored = client.objects[('landing-zone', key)]
        lineage = json.loads(
            client.objects[('landing-zone', stored['meta']['acquisition_metadata_key'])]['body']
        )
        assert lineage['acquisition']['local_filename'] == info['path'].name
        assert stored['body'] == info['path'].read_bytes()
    assert landing.ingest_dataset() == 0
    assert client.objects == original and len(client.uploads) == 2


def test_landing_upload_limit_counts_only_new_files(raw_dataset):
    client, files = raw_dataset
    assert landing.ingest_dataset(max_uploads=1) == 0
    assert len(client.uploads) == 1
    assert landing.ingest_dataset(max_uploads=1) == 0
    assert len(client.uploads) == 2
    assert landing.build_object_key(files[0]) != landing.build_object_key(files[1])


@pytest.mark.parametrize('conflict', ['species_id', 'modality', 'source_name'])
def test_landing_existing_identity_conflict_cannot_overwrite(raw_dataset, conflict):
    client, files = raw_dataset
    landing.ingest_dataset()
    key = landing.build_object_key(files[0])
    client.objects[('landing-zone', key)]['meta'][conflict] = 'different'
    before = dict(client.objects)
    assert landing.ingest_dataset() == 1
    assert client.objects == before and len(client.uploads) == 2


@pytest.mark.parametrize('state', ['complete', 'missing_target', 'wrong_species', 'invalid_json'])
def test_landing_completion_requires_valid_identity_and_existing_copy(raw_dataset, state):
    client, files = raw_dataset
    first = files[0]
    key = landing.build_object_key(first)
    target = 'persistent_landing/text/lynx_pardinus/a.txt'
    marker = dict(landing.build_object_metadata(first), persistent_key=target)
    if state == 'wrong_species':
        marker['species_id'] = 'bubo_bubo'
    if state != 'missing_target':
        client.put_object(Bucket='landing-zone', Key=target, Body=first['path'].read_bytes())
    client.put_object(
        Bucket='landing-zone',
        Key=landing.build_control_key(key),
        Body=b'broken{' if state == 'invalid_json' else json.dumps(marker).encode(),
    )
    assert landing.ingest_dataset() == (0 if state == 'complete' else 1)
    assert key not in client.uploads
    assert landing.build_object_key(files[1]) in client.uploads
    assert all(stream.closed for stream in client.streams)


def test_landing_missing_lineage_fails_without_upload(raw_dataset):
    client, files = raw_dataset
    files[0]['path'].with_name('_metadata.json').write_text('[]', encoding='utf-8')
    assert landing.ingest_dataset() == 2
    assert not client.objects


@pytest.fixture
def image_storage():
    client = MemoryStorage()
    key = 'persistent_landing/images/lynx_pardinus/a.png'
    client.put_object(
        Bucket='landing-zone',
        Key=key,
        Body=make_jpeg(),
        Metadata={
            'modality': 'images',
            'species_id': 'lynx_pardinus',
            'source_name': 'fixture',
            'asset_hash': 'source-hash',
        },
    )
    return client, key


def test_image_formatting_is_incremental_and_closes_source(image_storage):
    client, key = image_storage
    original = dict(client.objects[('landing-zone', key)])
    first = formatted.format_images(client)
    assert first['converted'] == 1 and first['errors'] == 0
    outputs = dict(client.objects)
    second = formatted.format_images(client)
    assert second['skipped'] == 1 and second['converted'] == second['errors'] == 0
    assert client.objects == outputs
    assert client.objects[('landing-zone', key)] == original
    assert all(stream.closed for stream in client.streams)


def test_image_dry_run_does_not_read_or_publish_media(image_storage):
    client, _ = image_storage
    before = dict(client.objects)
    result = formatted.format_images(client, dry_run=True, max_items=1)
    assert result['planned'] == 1 and result['errors'] == 0
    assert client.objects == before and not client.streams


@pytest.mark.parametrize(
    'field,value',
    [
        ('format_version', 'old'),
        ('jpeg_quality', '40'),
        ('source_persistent_key_encoded', 'another-source'),
        ('color_mode', 'cmyk'),
    ],
)
def test_image_contract_conflict_preserves_existing_output(image_storage, field, value):
    client, key = image_storage
    formatted.format_images(client)
    target = ('formatted-zone', formatted.build_formatted_key(key))
    client.objects[target]['meta'][field] = value
    before = dict(client.objects[target])
    result = formatted.format_images(client)
    assert result['errors'] == 1 and result['converted'] == result['skipped'] == 0
    assert client.objects[target] == before


@pytest.mark.parametrize('code', ['403', '503'])
def test_image_storage_error_is_not_treated_as_missing(image_storage, code):
    client, _ = image_storage
    head = client.head_object

    def unavailable(**kw):
        if kw['Bucket'] == 'formatted-zone':
            raise ClientError({'Error': {'Code': code}}, 'HeadObject')
        return head(**kw)

    client.head_object = unavailable
    result = formatted.format_images(client)
    assert result['errors'] == 1 and len(client.objects) == 1


@pytest.mark.parametrize('status', [None, 'accepted', 'error', 'rejected'])
def test_trusted_latest_rejection_blocks_indexing_but_preserves_bytes(status):
    client = MemoryStorage()
    key = 'text/lynx_pardinus/a.txt'
    client.put_object(
        Bucket='trusted-zone', Key=key, Body=b'original', Metadata={'quality_status': 'accepted'}
    )
    if status:
        client.put_object(
            Bucket='trusted-zone',
            Key='_quality/text/lynx_pardinus/a.json',
            Body=json.dumps({'status': status}).encode(),
        )
    repository = TrustedRepository(client, 'trusted-zone')
    before = dict(client.objects)
    if status == 'rejected':
        with pytest.raises(ValueError, match='subsequent rejection'):
            repository.source_info(key)
    else:
        assert repository.source_info(key)['meta']['_source_bucket'] == 'trusted-zone'
        assert repository.get(key) == b'original'
        assert list(repository.list('text', 'lynx_pardinus')) == [key]
    assert client.objects == before and all(stream.closed for stream in client.streams)


@pytest.mark.parametrize('fault', [None, 'missing', 'stale', 'parts', 'checksum'])
def test_reconciliation_detects_inconsistent_index_without_writes(tmp_path, fault):
    """Exercise the SQLite reader with independently constructed metadata faults."""
    client = MemoryStorage()
    key = 'images/lynx_pardinus/a.jpg'
    client.put_object(
        Bucket='trusted-zone', Key=key, Body=b'accepted', Metadata={'quality_status': 'accepted'}
    )
    dbfile = tmp_path / 'chroma.sqlite3'
    with sqlite3.connect(dbfile) as db:
        db.executescript("""
            CREATE TABLE collections (id TEXT, name TEXT);
            CREATE TABLE segments (id TEXT, collection TEXT);
            CREATE TABLE embeddings (id INTEGER, embedding_id TEXT, segment_id TEXT);
            CREATE TABLE embedding_metadata (id INTEGER, key TEXT, string_value TEXT, int_value INTEGER);
            INSERT INTO collections VALUES ('c', 'images');
            INSERT INTO segments VALUES ('s', 'c');
        """)
        if fault != 'missing':
            db.execute("INSERT INTO embeddings VALUES (1, 'vector', 's')")
            md = {
                'source_key': 'images/lynx_pardinus/old.jpg' if fault == 'stale' else key,
                'source_sha256': 'wrong'
                if fault == 'checksum'
                else hashlib.sha256(b'accepted').hexdigest(),
                'expected_parts': 2 if fault == 'parts' else 1,
                'part': 0,
            }
            for name, value in md.items():
                db.execute(
                    'INSERT INTO embedding_metadata VALUES (1, ?, ?, ?)',
                    (
                        name,
                        value if isinstance(value, str) else None,
                        value if isinstance(value, int) else None,
                    ),
                )
    before = dbfile.read_bytes()
    result = reconcile(
        TrustedRepository(client, 'trusted-zone'), tmp_path, {'collections': {'images': 'images'}}
    )
    assert result['trusted_assets'] == 1
    assert result['status'] == ('failed' if fault else 'completed')
    if fault:
        assert any(
            {
                'missing': 'missing asset',
                'stale': 'stale or unaccepted',
                'parts': 'incomplete parts',
                'checksum': 'checksum mismatch',
            }[fault]
            in p
            for p in result['problems']
        )
    else:
        assert result['total_vectors'] == 1 and result['problems'] == []
    assert dbfile.read_bytes() == before


def test_reconciliation_refuses_empty_dataset(tmp_path):
    with pytest.raises(ValueError, match='No accepted Trusted assets'):
        reconcile(TrustedRepository(MemoryStorage(), 'trusted-zone'), tmp_path, {'collections': {}})


@pytest.mark.parametrize('eligible,filtered', [(64, False), (65, False), (64, True), (65, True)])
def test_search_boundary_uses_filtered_vector_count(monkeypatch, eligible, filtered):
    from unittest.mock import Mock

    from multimodal_tasks.search import SearchService

    vector = [1.0] + [0.0] * 511
    ids = [f'v{i:03}' for i in range(eligible)]
    metadata = [{'asset_id': rid, 'modality': 'images'} for rid in ids]
    col = Mock()
    col.count.return_value = 500 if filtered else eligible
    col.get.side_effect = lambda include, **kw: (
        {'ids': ids}
        if not include
        else {
            'ids': ids,
            'embeddings': [vector] * eligible,
            'metadatas': metadata,
            'documents': [''] * eligible,
        }
    )
    col.query.return_value = {
        'ids': [ids[:8]],
        'metadatas': [metadata[:8]],
        'documents': [[''] * 8],
        'distances': [[0.0] * 8],
    }
    service = object.__new__(SearchService)
    monkeypatch.setattr(service, 'collection', lambda space: col)
    result = service.query_vector(vector, 'images', species='lynx_pardinus' if filtered else None)
    assert [r['asset_id'] for r in result] == ids[:8]
    assert all(r['score'] == pytest.approx(1.0) for r in result)
    assert col.query.call_count == int(eligible > 64)
    if filtered:
        assert all(
            call.kwargs['where'] == {'species_id': 'lynx_pardinus'}
            for call in col.get.call_args_list
        )
        if eligible > 64:
            assert col.query.call_args.kwargs['where'] == {'species_id': 'lynx_pardinus'}
