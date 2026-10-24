"""No MinIO server is needed: deterministic in-memory S3 double."""

from __future__ import annotations

import hashlib
import io
import json
from urllib.parse import quote

import numpy as np
import pytest
import soundfile as sf
from botocore.exceptions import ClientError

from trusted_zone.quality.audio_quality import audio_metrics
from trusted_zone.quality.text_quality import jaccard, normalize_text
from trusted_zone.pipeline_common import QualityFailure
from trusted_zone.validate_audio import run as run_audio
from trusted_zone.validate_text import run as run_text
from trusted_zone.reporting.generate_modality_report import generate

AUDIO_CFG = {
    'max_file_mb': 200,
    'min_duration_seconds': 0.01,
    'short_duration_warning_seconds': 0.5,
    'clipping_amplitude_threshold': 0.99,
    'clipping_pct_warning': 1.0,
    'low_rms_dbfs_warning': -55,
    'low_energy_dbfs_threshold': -50,
    'low_energy_window_pct_warning': 80,
    'dc_offset_warning': 0.02,
}
TEXT_CFG = {
    'max_file_mb': 4,
    'short_document_warning_words': 20,
    'alphanumeric_ratio_warning': 0.45,
    'near_duplicate_shingle_words': 5,
    'near_duplicate_min_shingles': 5,
    'near_duplicate_jaccard_warning': 0.90,
}


class FakePaginator:
    def __init__(self, store):
        self.store = store

    def paginate(self, *, Bucket, Prefix):
        items = [
            {'Key': key} for key in sorted(self.store.buckets[Bucket]) if key.startswith(Prefix)
        ]
        yield {'Contents': items}


class FakeS3:
    def __init__(self):
        self.buckets = {'formatted-zone': {}, 'trusted-zone': {}}

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return FakePaginator(self)

    def head_bucket(self, *, Bucket):
        if Bucket not in self.buckets:
            raise ClientError({'Error': {'Code': '404', 'Message': 'missing'}}, 'HeadBucket')
        return {}

    def create_bucket(self, *, Bucket):
        self.buckets[Bucket] = {}

    def put_object(self, *, Bucket, Key, Body, ContentLength, ContentType, Metadata):
        assert len(Body) == ContentLength
        self.buckets[Bucket][Key] = (bytes(Body), dict(Metadata), ContentType)

    def head_object(self, *, Bucket, Key):
        if Key not in self.buckets[Bucket]:
            raise ClientError({'Error': {'Code': '404', 'Message': 'missing'}}, 'HeadObject')
        data, meta, _ = self.buckets[Bucket][Key]
        return {
            'ContentLength': len(data),
            'Metadata': meta,
            'ETag': f'"{hashlib.md5(data).hexdigest()}"',
        }

    def get_object(self, *, Bucket, Key):
        data, meta, _ = self.buckets[Bucket][Key]
        return {'Body': io.BytesIO(data), 'Metadata': meta}

    def delete_object(self, *, Bucket, Key):
        self.buckets[Bucket].pop(Key, None)

    def add(self, modality: str, species: str, filename: str, data: bytes, **metadata):
        key = f'{modality}/{species}/{filename}'
        meta = {
            'modality': modality,
            'species_id': species,
            'source_name': 'test',
            'source_persistent_key_encoded': quote(f'persistent_landing/{key}', safe=''),
            **metadata,
        }
        self.buckets['formatted-zone'][key] = (data, meta, 'binary')
        return key


def make_flac(seconds=0.15, rate=32000, channels=2, silence=False):
    t = np.arange(round(seconds * rate)) / rate
    y = (
        np.zeros((len(t), channels))
        if silence
        else np.stack(
            [0.12 * np.sin(2 * np.pi * (400 + 70 * c) * t) for c in range(channels)], axis=1
        )
    )
    out = io.BytesIO()
    sf.write(out, y, rate, format='FLAC', subtype='PCM_16')
    return out.getvalue()


def test_audio_keeps_all_samples_channels_and_bytes():
    blob = make_flac(channels=2)
    metrics = audio_metrics(blob, AUDIO_CFG)
    assert metrics['channels'] == 2
    assert metrics['sample_rate_hz'] == 32000
    assert metrics['frames'] == 4800
    assert metrics['duration_seconds'] == 0.15
    assert len(metrics['decoded_pcm_sha256']) == 64
    assert 'digital_silence' not in metrics['flags']


def test_audio_warns_on_digital_silence_but_does_not_reject():
    assert 'digital_silence' in audio_metrics(make_flac(silence=True), AUDIO_CFG)['flags']


def test_audio_refuses_invalid_flac_and_empty_samples():
    with pytest.raises(QualityFailure, match='not_flac_container'):
        audio_metrics(b'invalid', AUDIO_CFG)


def test_audio_pipeline_deduplicates_within_species_preserves_other_species():
    s3 = FakeS3()
    blob = make_flac()
    a = s3.add('audio', 'species_a', 'a.flac', blob)
    b = s3.add('audio', 'species_a', 'b.flac', blob)
    c = s3.add('audio', 'species_b', 'c.flac', blob)
    result = run_audio(s3, AUDIO_CFG, '1', 'policy-a', report=False)
    assert (result['processed'], result['accepted'], result['rejected'], result['uploaded']) == (
        3,
        2,
        1,
        2,
    )
    assert s3.buckets['trusted-zone'][a][0] == blob
    assert b not in s3.buckets['trusted-zone']
    assert s3.buckets['trusted-zone'][c][0] == blob
    manifest = json.loads(s3.buckets['trusted-zone']['_quality/audio/species_a/b.json'][0])
    assert manifest['duplicate']['canonical_key'] == a
    cross = json.loads(s3.buckets['trusted-zone']['_quality/audio/species_b/c.json'][0])
    assert 'identical_audio_across_species' in cross['metrics']['flags']
    again = run_audio(s3, AUDIO_CFG, '1', 'policy-a', report=False)
    assert again.get('uploaded', 0) == 0
    assert again['unchanged_objects'] == 2
    assert again['unchanged_manifests'] == 3


def test_audio_dry_run_never_writes():
    s3 = FakeS3()
    s3.add('audio', 'species_a', 'a.flac', make_flac())
    result = run_audio(s3, AUDIO_CFG, '1', 'policy-a', dry_run=True, report=False)
    assert result['accepted'] == 1
    assert not s3.buckets['trusted-zone']


def test_text_keeps_unicode_punctuation_and_language():
    raw = 'El lince no canta.\n\nAño y Ñandú.\n'.encode('utf-8')
    clean, metrics, shingles = normalize_text(raw, TEXT_CFG)
    assert clean == raw
    assert 'no' in clean.decode('utf-8')
    assert 'Ñandú' in clean.decode('utf-8')
    assert metrics['words'] > 0


def test_text_nfc_normalization_and_empty_rejection():
    source = 'Cafe\u0301\r\n'.encode('utf-8')
    clean, metrics, _ = normalize_text(source, TEXT_CFG)
    assert clean == 'Café\n'.encode('utf-8')
    assert 'unicode_or_line_ending_normalized' in metrics['flags']
    with pytest.raises(QualityFailure, match='empty_text'):
        normalize_text(b'\n', TEXT_CFG)
    with pytest.raises(QualityFailure, match='invalid_utf8'):
        normalize_text(b'\xff\xfe', TEXT_CFG)


def test_pii_is_only_a_warning_and_not_disclosed_in_metrics():
    text = b'Write to john@example.org, sample: 192.168.0.1.\n'
    clean, metrics, _ = normalize_text(text, TEXT_CFG)
    assert clean == text
    assert 'possible_email_pii' in metrics['flags']
    assert metrics['possible_emails_count'] == 1
    assert 'john@example.org' not in json.dumps(metrics)


def test_jaccard_and_review_only_near_duplicates():
    assert jaccard(frozenset({'a', 'b'}), frozenset({'b', 'c'})) == pytest.approx(1 / 3)


def test_text_pipeline_exact_duplicate_and_second_run():
    s3 = FakeS3()
    text = (
        'Descripción de animal salvaje con dieta variada, reproducción, hábitat, '
        'comportamiento y distribución de fauna ibérica.\n'
    ).encode()
    a = s3.add('text', 'lynx_pardinus', 'a.txt', text)
    b = s3.add('text', 'lynx_pardinus', 'b.txt', text)
    c = s3.add('text', 'bubo_bubo', 'c.txt', text)
    first = run_text(s3, TEXT_CFG, '1', 'policy-t', report=False)
    assert first['accepted'] == 2
    assert first['rejected'] == 1
    assert s3.buckets['trusted-zone'][a][0] == text
    assert s3.buckets['trusted-zone'][c][0] == text
    assert b not in s3.buckets['trusted-zone']
    second = run_text(s3, TEXT_CFG, '1', 'policy-t', report=False)
    assert second['unchanged_objects'] == 2
    assert second.get('uploaded', 0) == 0


def test_audio_and_text_reports_have_html_plots_csv(tmp_path):
    s3 = FakeS3()
    s3.add('audio', 'bubo_bubo', 'a.flac', make_flac())
    s3.add('text', 'bubo_bubo', 'a.txt', b'This is a test about ecology and wildlife habitats.\n')
    run_audio(s3, AUDIO_CFG, '1', 'a', report=False)
    run_text(s3, TEXT_CFG, '1', 't', report=False)
    for modality, cfg in (('audio', AUDIO_CFG), ('text', TEXT_CFG)):
        path = generate(s3, modality, '1', cfg, output=tmp_path / modality)
        assert path.exists()
        assert (path.parent / 'metrics.csv').exists()
        assert (path.parent / 'summary.json').exists()
        assert (path.parent / 'species_before_after.png').exists()
        assert 'Accepted' in path.read_text(encoding='utf-8')
        assert json.loads((path.parent / 'summary.json').read_text())['accepted'] == 1
