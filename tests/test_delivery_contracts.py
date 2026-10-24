"""Final-review regressions for completeness, bounded I/O and invalid policies."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from exploitation_zone.vector_store import VectorStore
from orchestration import pipeline, storage
from trusted_zone.pipeline_common import validate_numeric_policy
from trusted_zone.validate_images import load_policy, POLICY_FILE


def complete_record(part):
    return {'part': part, 'expected_parts': 2, 'source_sha256': 'source', 'policy_sha256': 'policy'}


@pytest.mark.parametrize('parts', [[0, 0], [0, 2], [-1, 1], [False, 1], ['0', 1], [None, 1]])
def test_count_alone_does_not_prove_complete_segment_coverage(parts):
    collection = SimpleNamespace(
        get=lambda **kwargs: {
            'ids': ['first', 'second'],
            'metadatas': [complete_record(p) for p in parts],
        }
    )
    assert not VectorStore.is_complete(collection, 'asset', 'source', 'policy')


def test_complete_unordered_segments_are_reused_without_writes():
    collection = Mock()
    collection.get.return_value = {
        'ids': ['b', 'a'],
        'metadatas': [complete_record(1), complete_record(0)],
    }
    assert VectorStore.is_complete(collection, 'asset', 'source', 'policy')
    collection.upsert.assert_not_called()
    collection.delete.assert_not_called()


@pytest.mark.parametrize(
    'failure', ['missing_part', 'duplicate_id', 'missing_id', 'boolean_count', 'wrong_hash']
)
def test_malformed_completion_markers_trigger_repair(failure):
    data = {'ids': ['a', 'b'], 'metadatas': [complete_record(0), complete_record(1)]}
    if failure == 'missing_part':
        data['metadatas'][0].pop('part')
    elif failure == 'duplicate_id':
        data['ids'] = ['a', 'a']
    elif failure == 'missing_id':
        data['ids'] = ['a']
    elif failure == 'boolean_count':
        data['metadatas'][0]['expected_parts'] = True
    else:
        data['metadatas'][0]['source_sha256'] = 'different'
    collection = SimpleNamespace(get=lambda **kwargs: deepcopy(data))
    assert not VectorStore.is_complete(collection, 'asset', 'source', 'policy')


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf'), True])
def test_nonfinite_quality_thresholds_are_rejected(invalid, tmp_path):
    with pytest.raises(ValueError):
        validate_numeric_policy({'limit': invalid}, {'limit': (0, None)})
    policy = yaml.safe_load(POLICY_FILE.read_text(encoding='utf-8'))
    policy['images']['max_file_mb'] = invalid
    path = tmp_path / 'policy.yaml'
    path.write_text(yaml.safe_dump(policy), encoding='utf-8')
    with pytest.raises(ValueError):
        load_policy(path)


@pytest.mark.parametrize('invalid', ['nan', 'inf', '-inf', '0', '-1'])
def test_invalid_timeout_never_starts_a_child(invalid, monkeypatch, tmp_path):
    monkeypatch.setenv('ECOSENTINEL_STEP_TIMEOUT', invalid)
    child = Mock()
    monkeypatch.setattr(pipeline.subprocess, 'Popen', child)
    with pytest.raises(ValueError, match='finite and positive'):
        pipeline._run_process(['unused'], tmp_path, tmp_path / 'output.log')
    child.assert_not_called()


@pytest.mark.parametrize(
    'module,function',
    [
        ('formatted_zone.format_images', 'create_s3_client'),
        ('formatted_zone.format_audio', 'create_minio_client'),
        ('formatted_zone.format_text', 'create_minio_client'),
        ('trusted_zone.validate_images', 's3_client'),
        ('trusted_zone.pipeline_common', 'client_from_env'),
    ],
)
def test_zone_clients_share_bounded_storage_configuration(module, function, monkeypatch):
    from importlib import import_module

    sentinel = object()
    factory = Mock(return_value=sentinel)
    monkeypatch.setattr(storage, 'create_client', factory)
    assert getattr(import_module(module), function)() is sentinel
    factory.assert_called_once_with()
