"""Exercise real format converters and failure boundaries of the Landing state machine."""

from datetime import datetime, timezone
import io
import hashlib

import numpy as np
from PIL import Image
import pytest
import soundfile as sf

from landing_zone.persistent_landing import process_to_persistent as persistent
from formatted_zone.format_images import convert_to_jpeg
from formatted_zone.format_audio import convert_audio
from formatted_zone.format_text import convert_text
from exploitation_zone.encoders import normalize_vector


class Storage:
    def __init__(self):
        self.data = {}
        self.copies = 0
        self.deletes = 0

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.data:
            raise ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        data, meta = self.data[Key]
        return {
            'ContentLength': len(data),
            'Metadata': meta,
            'LastModified': datetime(2026, 1, 1, tzinfo=timezone.utc),
        }

    def get_object(self, Bucket, Key):
        return {'Body': io.BytesIO(self.data[Key][0])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.data[Key] = (bytes(Body), kwargs.get('Metadata', {}))

    def copy_object(self, Bucket, Key, CopySource, Metadata, **kwargs):
        self.copies += 1
        self.data[Key] = (self.data[CopySource['Key']][0], Metadata)

    def delete_object(self, Bucket, Key):
        self.deletes += 1
        del self.data[Key]


@pytest.fixture
def transfer(monkeypatch):
    s3 = Storage()
    data = b'original'
    key = 'temporal_landing/' + hashlib.sha256(data).hexdigest()[:16] + '__wild.txt'
    s3.data[key] = (
        data,
        {'modality': 'text', 'species_id': 'lynx_pardinus', 'source_name': 'test'},
    )
    monkeypatch.setattr(persistent, 'minio_client', s3)
    monkeypatch.setattr(persistent, 'list_temporal_objects', lambda: [key])
    return s3, key


def test_transfer_rerun_is_idempotent_and_retains_temporal_by_default(transfer):
    s3, key = transfer
    assert persistent.process_temporal_objects() == 0
    first = dict(s3.data)
    assert s3.copies == 1 and s3.deletes == 0
    assert persistent.process_temporal_objects() == 0
    assert s3.data == first and s3.copies == 1


def test_explicit_cleanup_only_after_verified_bytes_and_marker(transfer):
    s3, key = transfer
    assert persistent.process_temporal_objects(cleanup_temporal=True) == 0
    assert key not in s3.data and s3.deletes == 1
    assert any(k.startswith('persistent_landing/') for k in s3.data)
    assert any(k.startswith('_control/completed/') for k in s3.data)


def test_dangling_marker_does_not_remove_temporal(transfer):
    s3, key = transfer
    persistent.process_temporal_objects()
    dest = next(k for k in s3.data if k.startswith('persistent_landing/'))
    del s3.data[dest]
    assert persistent.process_temporal_objects(cleanup_temporal=True) == 1
    assert key in s3.data and s3.deletes == 0


def test_same_length_corruption_detected_before_cleanup(transfer):
    s3, key = transfer
    persistent.process_temporal_objects()
    dest = next(k for k in s3.data if k.startswith('persistent_landing/'))
    s3.data[dest] = (b'corrupt!', s3.data[dest][1])
    assert persistent.process_temporal_objects(cleanup_temporal=True) == 1
    assert key in s3.data


def test_failed_copy_does_not_publish_completion_marker(transfer):
    s3, key = transfer

    def fail(**kw):
        raise OSError('storage interrupted')

    s3.copy_object = fail
    assert persistent.process_temporal_objects(cleanup_temporal=True) == 1
    assert list(s3.data) == [key]


def test_marker_publication_failure_recovers_existing_copy(transfer):
    s3, key = transfer
    put = s3.put_object

    def fail(**kw):
        raise OSError('marker interrupted')

    s3.put_object = fail
    assert persistent.process_temporal_objects(cleanup_temporal=True) == 1
    assert key in s3.data
    s3.put_object = put
    assert persistent.process_temporal_objects(cleanup_temporal=True) == 0
    assert s3.copies == 1 and s3.deletes == 1


def test_persistent_cli_reports_errors(monkeypatch):
    monkeypatch.setattr('sys.argv', ['persistent'])
    monkeypatch.setattr(persistent, 'process_temporal_objects', lambda **kw: 2)
    assert persistent.main() == 1


@pytest.mark.parametrize(
    'mode,fmt', [('RGB', 'JPEG'), ('L', 'PNG'), ('RGBA', 'PNG'), ('P', 'PNG'), ('CMYK', 'JPEG')]
)
def test_canonical_image_modes(mode, fmt):
    image = Image.new(mode, (150, 160))
    source = io.BytesIO()
    image.save(source, format=fmt)
    output, detected = convert_to_jpeg(source.getvalue())
    with Image.open(io.BytesIO(output)) as result:
        assert result.format == 'JPEG' and result.mode == 'RGB' and result.size == (150, 160)


@pytest.mark.parametrize('blob', [b'', b'not an image', b'MZfake'])
def test_invalid_image_rejected(blob):
    with pytest.raises((ValueError, OSError)):
        convert_to_jpeg(blob)


@pytest.mark.parametrize(
    'extension,payload,expected',
    [
        ('.txt', 'Lince ibérico\r\n'.encode(), 'Lince ibérico'),
        ('.txt', 'Año y fauna'.encode('utf-16'), 'Año y fauna'),
        ('.html', b'<p>Fauna iberica</p><script>hidden()</script>', 'Fauna iberica'),
        ('.json', b'{"description":"Fauna iberica"}', 'Fauna iberica'),
        ('.jsonl', b'{"text":"Lince"}\n{"text":"Lobo"}', 'Lince'),
        ('.md', b'# Fauna\n\nLince iberico', 'Fauna'),
        ('.xml', b'<root><text>Fauna iberica</text></root>', 'Fauna iberica'),
    ],
)
def test_text_representations_are_canonical(extension, payload, expected):
    text, details = convert_text(payload, extension)
    assert expected in text and '\r' not in text and text.endswith('\n')
    assert not text.startswith('\ufeff') and 'hidden()' not in text


@pytest.mark.parametrize('channels,rate', [(1, 22050), (2, 44100), (2, 48000)])
def test_audio_formatting_preserves_duration_channels_and_rate(channels, rate):
    out = io.BytesIO()
    sf.write(out, np.ones((1000, channels)) * 0.1, rate, format='WAV', subtype='PCM_16')
    data, detected, decoder = convert_audio(out.getvalue(), '.wav', decoder='soundfile')
    info = sf.info(io.BytesIO(data))
    assert (info.frames, info.channels, info.samplerate, info.subtype) == (
        1000,
        channels,
        rate,
        'PCM_16',
    )


@pytest.mark.parametrize(
    'vector,dimension', [([0, 0], 2), ([float('nan'), 1], 2), ([float('inf')], 1), ([1, 2], 3)]
)
def test_invalid_embedding_outputs_rejected(vector, dimension):
    with pytest.raises(ValueError):
        normalize_vector(vector, dimension)
