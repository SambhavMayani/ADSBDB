"""Query inputs reuse Formatted/Trusted processing in memory, warn and never persist."""

import base64
import io
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest
import soundfile as sf
from PIL import Image

from exploitation_zone.indexer import load_config
from formatted_zone.format_audio import convert_audio
from formatted_zone.format_images import convert_to_jpeg
from multimodal_tasks.query_preparation import (
    PreparedQuery,
    prepare_query_audio,
    prepare_query_image,
    prepare_query_text,
)
from multimodal_tasks.rag import RagService
from multimodal_tasks.search import SearchService
from tests.test_rag import Search, generated
from webapp.server import make_handler, query_upload


def image_bytes(fmt='PNG', size=(256, 256), mode='RGB', color=(40, 120, 60), seed=7):
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    image = Image.fromarray(pixels).convert(mode) if color is None else Image.new(mode, size, color)
    stream = io.BytesIO()
    image.save(stream, format=fmt)
    return stream.getvalue()


def wav_bytes(seconds=0.5, rate=32000, channels=2, subtype='PCM_24', amplitude=0.3):
    t = np.arange(int(seconds * rate)) / rate
    signal = amplitude * np.sin(2 * np.pi * 440 * t)
    stream = io.BytesIO()
    sf.write(stream, np.stack([signal] * channels, axis=1), rate, format='WAV', subtype=subtype)
    return stream.getvalue()


class RecordingEncoders:
    def __init__(self):
        self.images, self.audio = [], []

    def release_all(self):
        pass

    def clip_image(self, data):
        self.images.append(data)
        return [1.0] + [0.0] * 511

    def clap_audio(self, signal):
        self.audio.append(signal)
        return [1.0] + [0.0] * 511


def offline_service(tmp_path, monkeypatch):
    """SearchService without opening any index: only the preparation path is exercised."""
    encoders = RecordingEncoders()
    service = SearchService(
        tmp_path / 'query', client=object(), config=load_config(), encoders=encoders
    )
    row = {'asset_id': 'a', 'modality': 'images', 'score': 0.5, 'id': 'a'}
    monkeypatch.setattr(service, 'query_space', lambda vector, space, **kwargs: [dict(row)])
    return service, encoders


def test_uploaded_image_receives_the_exact_formatted_jpeg():
    raw = image_bytes('PNG', mode='RGBA', color=(10, 20, 30, 0))
    prepared = prepare_query_image(raw)
    assert prepared.data == convert_to_jpeg(raw)[0]
    assert prepared.report['source_format'] == 'png'
    assert prepared.report['canonical_format'] == 'jpeg_rgb_q95'
    assert prepared.report['persisted'] is False
    assert len(prepared.report['input_sha256']) == 64
    with Image.open(io.BytesIO(prepared.data)) as image:
        assert image.format == 'JPEG' and image.mode == 'RGB'
        # Transparent pixels are composited on white, exactly like the indexed corpus.
        assert min(image.getpixel((5, 5))) > 240


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG', 'WEBP', 'BMP', 'GIF', 'TIFF'])
def test_pipeline_image_formats_are_accepted_for_queries(fmt):
    prepared = prepare_query_image(image_bytes(fmt, color=None))
    assert prepared.data.startswith(b'\xff\xd8') and prepared.report['source_format'] == fmt.lower()


def test_image_formats_outside_the_pipeline_are_rejected():
    stream = io.BytesIO()
    Image.new('RGB', (64, 64), 'green').save(stream, format='ICO')
    with pytest.raises(ValueError, match='Unsupported image format'):
        prepare_query_image(stream.getvalue())
    with pytest.raises(ValueError, match='invalid image'):
        prepare_query_image(b'not an image at all')


def test_trusted_quality_signals_warn_but_never_block_a_query():
    flat_small = image_bytes('PNG', size=(64, 64), color=(5, 5, 5))
    prepared = prepare_query_image(flat_small)
    flags = prepared.report['flags']
    # Corpus rejection (dimensions) and corpus warnings all become user warnings.
    assert {'low_sharpness', 'low_brightness', 'dimensions_too_small'} <= set(flags)
    assert any('baja nitidez' in warning for warning in prepared.report['warnings'])
    assert prepared.data.startswith(b'\xff\xd8')
    assert 'possible_watermark' not in flags  # noisy heuristic deliberately not reused


def test_sharp_photograph_like_image_has_no_sharpness_warning():
    prepared = prepare_query_image(image_bytes('PNG', color=None))
    assert 'low_sharpness' not in prepared.report['flags']


def test_stored_trusted_jpeg_is_reused_without_reencoding():
    stored = convert_to_jpeg(image_bytes('PNG', color=None))[0]
    prepared = prepare_query_image(stored, already_canonical=True)
    assert prepared.data == stored
    assert prepared.report['steps'][0] == 'trusted_image_reused_without_reencoding'


def test_uploaded_audio_receives_the_exact_formatted_flac_pcm16():
    raw = wav_bytes(subtype='PCM_24')
    prepared = prepare_query_audio(raw)
    assert prepared.data == convert_audio(raw, '.wav', decoder='soundfile')[0]
    info = sf.info(io.BytesIO(prepared.data))
    assert (info.format, info.subtype, info.samplerate, info.channels) == (
        'FLAC',
        'PCM_16',
        32000,
        2,
    )
    assert prepared.report['source_format'] == 'wav' and prepared.report['flags'] == []


def test_audio_quality_signals_warn_but_never_block_a_query():
    quiet = prepare_query_audio(wav_bytes(seconds=0.3, subtype='PCM_16', amplitude=0.0005))
    assert {'low_rms', 'short_recording'} <= set(quiet.report['flags'])
    tiny = prepare_query_audio(wav_bytes(seconds=0.004, subtype='PCM_16'))
    # Below the Trusted minimum duration: rejected in the corpus, only a warning here.
    assert tiny.report['flags'][0] == 'duration_below_minimum' and tiny.report['warnings']


def test_audio_needing_temporary_files_or_unknown_bytes_is_rejected():
    with pytest.raises(ValueError, match='in-memory'):
        prepare_query_audio(b'\x00\x00\x00\x18ftypM4A ' + b'\x00' * 64)
    with pytest.raises(ValueError):
        prepare_query_audio(b'not audio')


def test_text_query_follows_the_canonical_text_contract():
    assert prepare_query_text('  Hábitat del lince\r\nibérico\x07 ') == (
        'Hábitat del lince\nibérico'
    )
    decomposed = 'ibérico'
    assert prepare_query_text(decomposed) == 'ibérico'
    assert prepare_query_text('\x00\x01') == ''


def test_search_prepares_media_once_and_returns_a_report(tmp_path, monkeypatch):
    service, encoders = offline_service(tmp_path, monkeypatch)
    raw = image_bytes('PNG', mode='RGBA', color=(0, 0, 0, 0))
    rows, report = service.media_with_report(raw, 'images', mixed=True)
    assert rows and encoders.images == [convert_to_jpeg(raw)[0]]
    assert report['canonical_format'] == 'jpeg_rgb_q95'
    prepared = prepare_query_image(raw)
    assert service.media(prepared, 'images') and encoders.images[-1] == prepared.data
    with pytest.raises(ValueError, match='modality'):
        service.media(prepared, 'audio')


def test_search_audio_query_uses_the_canonical_flac(tmp_path, monkeypatch):
    service, encoders = offline_service(tmp_path, monkeypatch)
    rows, report = service.media_with_report(wav_bytes(subtype='FLOAT'), 'audio')
    assert rows and encoders.audio and report['canonical_format'] == 'flac_pcm16'
    with pytest.raises(ValueError, match='Unsupported or invalid audio'):
        service.media(b'not audio', 'audio')


def test_search_text_normalization_reaches_the_encoder(tmp_path, monkeypatch):
    service, _ = offline_service(tmp_path, monkeypatch)
    seen = []

    class Model:
        def encode(self, text, **kwargs):
            seen.append(text)
            return [1.0] + [0.0] * 383

    service.encoders.sentence_transformer = lambda key: Model()
    service.text('lince ibérico\r\n', mode='text')
    assert seen == ['query: lince ibérico']
    with pytest.raises(ValueError):
        service.text('\x00\x01', mode='text')


def test_upload_validation_returns_400_class_errors_not_service_failures():
    for payload in (
        {'data': base64.b64encode(b'not an image').decode(), 'modality': 'images'},
        {'data': base64.b64encode(b'not audio').decode(), 'modality': 'audio'},
    ):
        with pytest.raises(ValueError):
            query_upload(payload)
    stream = io.BytesIO()
    Image.new('RGB', (32, 32)).save(stream, format='ICO')
    with pytest.raises(ValueError, match='Unsupported image format'):
        query_upload({'data': base64.b64encode(stream.getvalue()).decode(), 'modality': 'images'})
    gif = image_bytes('GIF', size=(32, 32))
    assert query_upload({'data': base64.b64encode(gif).decode(), 'modality': 'images'}) == gif


def test_rag_uses_the_prepared_image_and_keeps_warnings_out_of_the_prompt():
    seen, prompts = [], []

    def captioner(data, **kwargs):
        seen.append(data)
        return 'a lynx in a forest'

    def generator(messages, policy):
        prompts.append(json.dumps(messages, ensure_ascii=False))
        return generated(messages, policy)

    service = Search()
    calls = []
    original = service.media

    def media(data, *args, **kwargs):
        calls.append(data)
        return original(data, *args, **kwargs)

    service.media = media
    raw = image_bytes('PNG', size=(64, 64), color=(5, 5, 5))
    result = RagService(service, captioner=captioner, generator=generator).answer(
        '¿Cuál es su hábitat?', image=raw
    )
    canonical = convert_to_jpeg(raw)[0]
    assert seen == [canonical]
    assert isinstance(calls[0], PreparedQuery) and calls[0].data == canonical
    assert result['input_sha256'] == result['query_preparation']['input_sha256']
    assert 'low_sharpness' in result['query_preparation']['flags']
    assert result['status'] == 'answered'
    assert not any('nitidez' in prompt for prompt in prompts)


def test_rag_reuses_a_stored_trusted_jpeg_byte_for_byte():
    stored = convert_to_jpeg(image_bytes('PNG', color=None))[0]
    seen = []

    def captioner(data, **kwargs):
        seen.append(data)
        return 'a lynx in a forest'

    RagService(Search(), captioner=captioner, generator=generated).answer(
        '¿Cuál es su hábitat?', image=stored, input_source_key='images/lynx_pardinus/a.jpg'
    )
    assert seen == [stored]


@pytest.mark.parametrize('modality', ['images', 'audio'])
def test_direct_query_rejects_byte_budget_before_conversion(monkeypatch, modality):
    import multimodal_tasks.query_preparation as preparation

    raw = image_bytes() if modality == 'images' else wav_bytes()
    monkeypatch.setattr(preparation, 'MAX_QUERY_BYTES', len(raw) - 1)

    def must_not_convert(*args, **kwargs):
        raise AssertionError('Oversized input reached the converter')

    monkeypatch.setattr(preparation, 'convert_to_jpeg', must_not_convert)
    monkeypatch.setattr(preparation, 'convert_audio', must_not_convert)
    prepare = prepare_query_image if modality == 'images' else prepare_query_audio
    with pytest.raises(ValueError, match='10 MiB'):
        prepare(raw)


def test_direct_image_pixel_budget_precedes_conversion(monkeypatch):
    import multimodal_tasks.query_preparation as preparation

    raw = image_bytes(size=(256, 256))
    monkeypatch.setattr(preparation, 'MAX_QUERY_PIXELS', 256 * 256 - 1)

    def must_not_convert(*args, **kwargs):
        raise AssertionError('Oversized dimensions reached the converter')

    monkeypatch.setattr(preparation, 'convert_to_jpeg', must_not_convert)
    with pytest.raises(ValueError, match='20 megapixels'):
        prepare_query_image(raw)


@pytest.mark.parametrize('seconds,channels', [(30.01, 1), (0.1, 9)])
def test_direct_audio_limits_precede_conversion(monkeypatch, seconds, channels):
    import multimodal_tasks.query_preparation as preparation

    raw = wav_bytes(seconds=seconds, rate=8000, channels=channels)

    def must_not_convert(*args, **kwargs):
        raise AssertionError('Oversized audio reached the converter')

    monkeypatch.setattr(preparation, 'convert_audio', must_not_convert)
    with pytest.raises(ValueError, match='30 seconds / 8 channels'):
        prepare_query_audio(raw)


def test_rag_invalid_image_is_a_value_error():
    with pytest.raises(ValueError, match='invalid image'):
        RagService(Search(), generator=generated).answer('What animal?', image=b'not image')


@pytest.mark.e2e
def test_http_upload_returns_results_and_query_preparation(tmp_path, monkeypatch):
    service, _ = offline_service(tmp_path, monkeypatch)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/upload'

    def post(data, modality):
        body = {'data': base64.b64encode(data).decode(), 'modality': modality, 'limit': 3}
        return urlopen(
            Request(
                url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}
            )
        )

    try:
        with post(image_bytes('PNG', size=(64, 64), color=(5, 5, 5)), 'images') as response:
            body = json.load(response)
        assert body['results'] and body['query_preparation']['persisted'] is False
        assert body['query_preparation']['warnings']
        with pytest.raises(HTTPError) as error:
            post(b'PK\x03\x04 renamed archive', 'images')
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
