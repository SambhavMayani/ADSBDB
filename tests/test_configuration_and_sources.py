"""Configuration, provider failures, atomic metadata and offline storage boundaries."""

import json
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest
import requests
import yaml

from exploitation_zone.indexer import load_config
from orchestration.files import atomic_json_write
from orchestration import storage, pipeline
from landing_zone.data_acquisition import download_wikimedia_images as images
from landing_zone.data_acquisition import download_species_texts as texts
from landing_zone.temporal_landing.security_gate import inspect_file, read_config


@pytest.mark.parametrize(
    'section,key,value',
    [
        ('runtime', 'text_batch_size', 0),
        ('runtime', 'text_batch_size', True),
        ('runtime', 'text_batch_size', '2'),
        ('chunks', 'e5_overlap', 320),
        ('chunks', 'e5_overlap', -1),
        ('chunks', 'e5_tokens', True),
        ('chunks', 'e5_tokens', 501),
        ('chunks', 'clip_tokens', 121),
        ('chunks', 'clap_text_tokens', 71),
        ('chunks', 'audio_sample_rate', 44100),
        ('chunks', 'audio_window_seconds', 0),
        ('chunks', 'audio_window_seconds', 11),
        ('chunks', 'audio_window_seconds', True),
        ('models', 'audio', ''),
        ('models', 'text', None),
        ('collections', 'images', ''),
        ('collections', 'images', 'ecosentinel_audio_clap_v1'),
    ],
)
def test_bad_policies_fail_before_creating_storage(tmp_path, section, key, value):
    cfg = load_config()
    cfg.setdefault(section, {})[key] = value
    file = tmp_path / 'bad.yaml'
    file.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    with pytest.raises(ValueError):
        load_config(file)
    assert not (tmp_path / 'index').exists()


@pytest.mark.parametrize('bad', [float('nan'), {'unsupported'}])
def test_atomic_metadata_failure_preserves_previous_registry(tmp_path, bad):
    path = tmp_path / '_metadata.json'
    atomic_json_write(path, [{'id': 'original'}])
    before = path.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        atomic_json_write(path, bad)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))


def test_atomic_replace_failure_preserves_registry(tmp_path, monkeypatch):
    path = tmp_path / 'metadata.json'
    atomic_json_write(path, {'before': 1})

    def fail(*a):
        raise PermissionError('locked destination')

    monkeypatch.setattr('orchestration.files.os.replace', fail)
    with pytest.raises(PermissionError):
        atomic_json_write(path, {'after': 2})
    assert json.loads(path.read_text()) == {'before': 1}
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize(
    'name',
    ['CON.jpg', 'nul.png', 'AUX.webp', 'COM1.jpg', 'LPT9.jpeg', 'a:b?.jpg', 'x' * 300 + '.jpg'],
)
def test_wikimedia_names_are_windows_safe(name):
    result = images.safe_filename(name)
    assert len(result) <= 140 and not any(c in result for c in '<>:"/\\|?*')
    assert result.split('.')[0].upper() not in {'CON', 'NUL', 'AUX', 'COM1', 'LPT9'}
    assert Path(result).suffix == Path(name).suffix


def test_wikimedia_provider_error_is_operational_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(images, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(images, 'get_category_members', lambda *a: ['File:lynx.jpg'])

    def fail(*a):
        raise requests.HTTPError('provider unavailable')

    monkeypatch.setattr(images, 'get_image_info', fail)
    assert (
        images.process_species(None, {'id': 'lynx_pardinus', 'scientific_name': 'Lynx pardinus'}, 1)
        == 1
    )


def test_wikimedia_corrupt_registry_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(images, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(images, 'get_category_members', lambda *a: [])
    folder = tmp_path / 'lynx_pardinus'
    folder.mkdir()
    path = folder / '_metadata.json'
    path.write_text('{broken')
    with pytest.raises(ValueError):
        images.process_species(None, {'id': 'lynx_pardinus', 'scientific_name': 'Lynx pardinus'}, 1)
    assert path.read_text() == '{broken'


def test_text_provider_error_is_operational_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(texts, 'OUTPUT_ROOT', tmp_path)

    def fail(*a):
        raise requests.HTTPError('provider unavailable')

    monkeypatch.setattr(texts, 'acquire_wikipedia', fail)
    assert (
        texts.process_species(
            None,
            {'id': 'lynx_pardinus', 'scientific_name': 'Lynx pardinus'},
            ['wikipedia'],
            ['en'],
            1,
            1,
            {},
        )
        == 1
    )


@pytest.mark.parametrize('module', [images, texts])
def test_provider_main_propagates_stage_failure(module, monkeypatch):
    monkeypatch.setattr(module, 'load_species', lambda: [{'id': 'lynx_pardinus'}])
    monkeypatch.setattr(module, 'create_session', lambda: None)
    monkeypatch.setattr(module, 'process_species', lambda *a: 1)
    monkeypatch.setattr(sys, 'argv', ['download'])
    assert module.main() == 1


@pytest.mark.parametrize(
    'code,expected', [('eng', 'en'), ('spa', 'es'), ('en', 'en'), ('xx', 'xx'), (None, None)]
)
def test_provider_languages_remain_traceable(code, expected):
    assert texts.normalize_language(code) == expected


@pytest.mark.parametrize(
    'url,expected',
    [
        (None, None),
        ('https://creativecommons.org/publicdomain/zero/1.0/', 'CC0 1.0'),
        ('https://creativecommons.org/licenses/by-sa/4.0/', 'CC BY-SA 4.0'),
        ('https://example.org/license', None),
    ],
)
def test_license_metadata_is_not_invented(url, expected):
    assert texts.license_name_from_url(url) == expected


def test_text_metadata_retains_only_assets_that_exist(tmp_path):
    (tmp_path / 'a.txt').write_text('fauna')
    file = tmp_path / '_metadata.json'
    atomic_json_write(file, [{'local_filename': 'a.txt'}, {'local_filename': 'missing.txt'}])
    assert texts.load_metadata(file, tmp_path) == [{'local_filename': 'a.txt'}]


def test_explicit_unicode_bom_is_accepted_by_security_gate(tmp_path):
    file = tmp_path / 'fauna.txt'
    file.write_bytes('Fauna ibérica'.encode('utf-16'))
    assert inspect_file(file, 'text', read_config()).allowed


def test_shared_storage_requires_credentials_before_network(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv', lambda *a: None)
    monkeypatch.delenv('MINIO_ROOT_USER', raising=False)
    monkeypatch.delenv('MINIO_ROOT_PASSWORD', raising=False)
    with pytest.raises(RuntimeError):
        storage.create_client()


def test_shared_storage_endpoint_and_bounded_retries(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv', lambda *a: None)
    monkeypatch.setenv('MINIO_ROOT_USER', 'test')
    monkeypatch.setenv('MINIO_ROOT_PASSWORD', 'dummy_test_only')
    monkeypatch.setenv('S3_ENDPOINT_URL', 'http://127.0.0.1:19000')
    factory = Mock(return_value='client')
    monkeypatch.setattr('boto3.client', factory)
    assert storage.create_client() == 'client'
    opts = factory.call_args.kwargs
    assert opts['endpoint_url'] == 'http://127.0.0.1:19000'
    assert opts['config'].connect_timeout == 5 and opts['config'].read_timeout == 60


def test_lazy_client_connects_once(monkeypatch):
    factory = Mock(return_value=Mock())
    monkeypatch.setattr(storage, 'create_client', factory)
    client = storage.LazyClient()
    assert not factory.called
    client.list_buckets()
    client.list_buckets()
    assert factory.call_count == 1


def test_child_logs_redact_configured_secrets(tmp_path, monkeypatch):
    secret = 'only_for_redaction_test_8675309'
    monkeypatch.setenv('DEMO_API_KEY', secret)
    script = tmp_path / 'echo.py'
    script.write_text("import os\nprint(os.environ['DEMO_API_KEY'])\n")
    log = tmp_path / 'out.log'
    assert pipeline._run_process([sys.executable, str(script)], tmp_path, log) == 0
    assert secret not in log.read_text() and '[REDACTED]' in log.read_text()
