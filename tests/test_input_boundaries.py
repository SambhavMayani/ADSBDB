"""Adversarial input fixtures: generated locally, never uploaded or executed."""

from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest
from PIL import Image

from tests.test_trusted_images import FakeS3, make_jpeg, upload_formatted
from landing_zone.temporal_landing.security_gate import inspect_file, read_config
from trusted_zone.quality.image_quality import assess_watermark
from trusted_zone.validate_images import load_policy, run


@pytest.mark.parametrize(
    'header',
    [b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'],
)
def test_other_active_binary_headers_are_blocked_as_text(tmp_path, header):
    path = tmp_path / 'description.txt'
    path.write_bytes(header + b'harmless fixture')
    verdict = inspect_file(path, 'text', read_config())
    assert not verdict.allowed
    assert verdict.reason == 'executable_or_active_binary_detected'


@pytest.mark.parametrize(
    'modality,name', [('images', 'a.jpg'), ('audio', 'a.wav'), ('text', 'a.txt')]
)
def test_empty_inputs_are_blocked(tmp_path, modality, name):
    path = tmp_path / name
    path.write_bytes(b'')
    verdict = inspect_file(path, modality, read_config())
    assert not verdict.allowed and verdict.reason == 'empty_file'


def test_real_png_renamed_jpeg_is_a_signature_mismatch(tmp_path):
    path = tmp_path / 'frog.jpg'
    Image.new('RGB', (160, 160)).save(path, format='PNG')
    verdict = inspect_file(path, 'images', read_config())
    assert not verdict.allowed and verdict.reason == 'file_signature_mismatch'


def test_jpeg_signature_does_not_hide_a_corrupt_payload(tmp_path):
    path = tmp_path / 'frog.jpg'
    path.write_bytes(b'\xff\xd8\xff' + b'not a decodable JPEG')
    verdict = inspect_file(path, 'images', read_config())
    assert not verdict.allowed and verdict.reason == 'image_header_invalid'


def test_decodable_image_exceeding_pixel_budget_is_blocked(tmp_path):
    path = tmp_path / 'frog.jpg'
    path.write_bytes(make_jpeg())
    policy = read_config()
    policy['max_image_megapixels'] = 0.05
    verdict = inspect_file(path, 'images', policy)
    assert not verdict.allowed and verdict.reason == 'safety_pixel_limit_exceeded'


@pytest.mark.parametrize(
    'setting,value,reason',
    [
        ('max_archive_entries', 1, 'archive_entry_limit_exceeded'),
        ('max_archive_uncompressed_mb', 0.001, 'archive_uncompressed_limit_exceeded'),
        ('max_archive_ratio', 2, 'archive_compression_ratio_exceeded'),
    ],
)
def test_document_archives_have_bounded_expansion(tmp_path, setting, value, reason):
    path = tmp_path / 'description.docx'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', 'a' * 4096)
        archive.writestr('[Content_Types].xml', '<Types/>')
    policy = read_config()
    policy[setting] = value
    verdict = inspect_file(path, 'text', policy)
    assert not verdict.allowed and verdict.reason == reason
    assert sorted(p.name for p in tmp_path.iterdir()) == ['description.docx']


def test_invalid_document_archive_is_blocked_without_extraction(tmp_path):
    path = tmp_path / 'description.docx'
    path.write_bytes(b'PK\x03\x04invalid archive')
    verdict = inspect_file(path, 'text', read_config())
    assert not verdict.allowed and verdict.reason == 'invalid_archive'


def test_watermark_heuristic_distinguishes_corner_edges_from_flat_image():
    config = load_policy()[1]
    flat = np.full((256, 256, 3), 127, dtype=np.uint8)
    overlay = flat.copy()
    # Sharp synthetic corner stripes exercise the heuristic, not OCR accuracy.
    overlay[:50:4, :50] = 0
    overlay[2:50:4, :50] = 255
    assert assess_watermark(flat, 'lightweight', config)['status'] == 'no_indicator'
    assert assess_watermark(overlay, 'lightweight', config)['status'] == 'possible'


def test_optional_ocr_failure_falls_back_and_reports_its_method(monkeypatch):
    import pytesseract

    def unavailable(*args, **kwargs):
        raise RuntimeError('Synthetic OCR timeout')

    monkeypatch.setattr(pytesseract, 'image_to_data', unavailable)
    result = assess_watermark(np.zeros((256, 256, 3), dtype=np.uint8), 'advanced', load_policy()[1])
    assert result['method'] == 'lightweight_fallback'
    assert result['status'] == 'no_indicator'


def test_possible_watermark_retains_original_bytes_and_records_warning(monkeypatch):
    import trusted_zone.validate_images as validator

    client = FakeS3()
    data = make_jpeg(seed=91)
    key = upload_formatted(client, 'lynx_pardinus', 'overlay', data)
    monkeypatch.setattr(
        validator,
        'watermark_on_bytes',
        lambda *args: {'method': 'controlled_fixture', 'status': 'possible', 'signals': 1},
    )
    result = run(client, load_policy()[1], '1', report=False)
    assert result['accepted'] == 1 and result.get('rejected', 0) == 0
    assert client.objects[('trusted-zone', key)]['body'] == data
    manifest = json.loads(
        client.objects[('trusted-zone', '_quality/images/lynx_pardinus/overlay.json')]['body']
    )
    assert manifest['status'] == 'accepted'
    assert 'possible_watermark' in manifest['metrics']['flags']


@pytest.mark.parametrize(
    'data', [b'not an image', make_jpeg()[:-200]], ids=['unknown-format', 'truncated-jpeg']
)
def test_corrupt_formatted_image_is_rejected_with_a_quality_manifest(data):
    client = FakeS3()
    key = upload_formatted(client, 'lynx_pardinus', 'corrupt', data)
    result = run(client, load_policy()[1], '1', report=False)
    assert result['rejected'] == 1
    assert ('trusted-zone', key) not in client.objects
    manifest = json.loads(
        client.objects[('trusted-zone', '_quality/images/lynx_pardinus/corrupt.json')]['body']
    )
    assert manifest['status'] == 'rejected'
    assert manifest['reason'].startswith('invalid_image_payload:')
    assert result.get('errors', 0) == 0


def test_later_corruption_does_not_delete_previously_accepted_image():
    client = FakeS3()
    original = make_jpeg(seed=93)
    key = upload_formatted(client, 'lynx_pardinus', 'changed', original)
    assert run(client, load_policy()[1], '1', report=False)['accepted'] == 1
    upload_formatted(client, 'lynx_pardinus', 'changed', b'broken replacement')
    result = run(client, load_policy()[1], '1', report=False)
    assert result['rejected'] == 1
    assert client.objects[('trusted-zone', key)]['body'] == original
