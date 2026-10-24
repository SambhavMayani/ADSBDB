"""Offline model revision safety: no downloads and no GPU/model inference."""

import copy
import json
from unittest.mock import Mock

import pytest

from exploitation_zone import encoders as module
from exploitation_zone import prepare_models
from exploitation_zone.contracts import policy_fingerprint
from exploitation_zone.indexer import load_config


@pytest.mark.parametrize('key', ['image', 'image_text', 'text', 'audio'])
def test_legacy_revision_resolves_to_observed_commit_without_changing_contract(key):
    config = load_config()
    before = copy.deepcopy(config)
    fingerprint = policy_fingerprint(config, '', 'image_text')
    revision = module.Encoders(config)._revision(key)
    assert len(revision) == 40
    assert config == before
    assert policy_fingerprint(config, '', 'image_text') == fingerprint


def test_explicit_revision_wins_over_legacy_manifest():
    config = load_config()
    config['revisions']['text'] = 'a' * 40
    assert module.Encoders(config)._revision('text') == 'a' * 40


@pytest.mark.parametrize('revision', ['main', '', True, 123, 'a' * 39])
def test_mutable_or_malformed_model_revisions_are_rejected(revision):
    config = load_config()
    config['revisions']['text'] = revision
    with pytest.raises(ValueError, match='immutable'):
        module.Encoders(config)._revision('text')


def test_unknown_unpinned_model_is_rejected():
    config = load_config()
    config['models']['text'] = 'other/unpinned'
    with pytest.raises(ValueError, match='immutable'):
        module.Encoders(config)._revision('text')


def test_corrupt_manifest_is_not_silently_ignored(tmp_path, monkeypatch):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/model_manifest.json').write_text('{broken')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    with pytest.raises(json.JSONDecodeError):
        module.Encoders(load_config())._revision('text')


@pytest.mark.parametrize('download', [False, True])
def test_preparation_uses_cpu_and_requires_explicit_download(download, monkeypatch):
    adapter = Mock()
    factory = Mock(return_value=adapter)
    monkeypatch.setattr(prepare_models, 'Encoders', factory)
    for key in ('ECOSENTINEL_ALLOW_MODEL_DOWNLOAD', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
        monkeypatch.setenv(key, 'initial')
    assert prepare_models.main(['--download'] if download else []) == 0
    assert factory.call_args.kwargs['device'] == 'cpu'
    assert adapter.sentence_transformer.call_count == 3
    adapter.clap_model.assert_called_once()
    assert prepare_models.os.environ['ECOSENTINEL_ALLOW_MODEL_DOWNLOAD'] == (
        '1' if download else '0'
    )
    assert prepare_models.os.environ['HF_HUB_OFFLINE'] == ('0' if download else '1')
