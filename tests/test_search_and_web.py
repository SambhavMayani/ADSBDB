"""Real Chroma on temporary paths plus HTTP and retrieval edge cases."""

import base64
import io
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
import pytest
from PIL import Image
from exploitation_zone.contracts import policy_fingerprint
from exploitation_zone.indexer import load_config
from multimodal_tasks.search import SearchService, collapse, fuse_rankings
from multimodal_tasks.generate import describe
from webapp.server import make_handler, query_upload, validate_key


def test_task2_shared_space_returns_both_modalities(search):
    rows = search.text('lynx', mode='image_text', limit=6)
    assert {r['modality'] for r in rows} == {'images', 'text'}


def test_audio_text_mixed_space_returns_both_modalities(search):
    assert {r['modality'] for r in search.text('owl', mode='audio_text', limit=6)} == {
        'audio',
        'text',
    }


@pytest.mark.parametrize('space,kind', [('images', 'images'), ('audio', 'audio'), ('text', 'text')])
def test_task1_excludes_entire_reference_asset(search, space, kind):
    rows = search.by_record(kind + '0', space, limit=4)
    assert rows and all(r['asset_id'] != kind + '0' for r in rows)
    assert all(r['modality'] == kind for r in rows)


def test_filters_and_no_matches(search):
    rows = search.text('lynx', mode='image_text', species='lynx_pardinus', modality='images')
    assert len(rows) == 2 and all(
        r['species_id'] == 'lynx_pardinus' and r['modality'] == 'images' for r in rows
    )
    assert search.text('x', mode='text', species='missing') == []


def test_small_collection_uses_exact_cosine_without_hnsw(search, monkeypatch):
    collection = search.collection('images')
    monkeypatch.setattr(search, 'collection', lambda space: collection)

    def no_hnsw(**kwargs):
        raise AssertionError('Tiny collections must not require an HNSW disk segment')

    monkeypatch.setattr(collection, 'query', no_hnsw)
    rows = search.query_vector([1.0] + [0.0] * 511, 'images')
    assert [row['id'] for row in rows] == ['images0', 'images1', 'images2']
    assert rows[0]['score'] == pytest.approx(1.0)
    assert rows[1]['score'] == pytest.approx(1 / (1.01**0.5))


def test_larger_collection_uses_real_hnsw(tmp_path, monkeypatch):
    from exploitation_zone.vector_store import VectorStore

    cfg = load_config()
    path = tmp_path / 'large'
    store = VectorStore(path)
    collection = store.get_collection(
        cfg['collections']['images'], 512, policy_fingerprint(cfg, '', 'images')
    )
    collection.add(
        ids=[str(i) for i in range(70)],
        embeddings=[[1.0, i * 0.02] + [0.0] * 510 for i in range(70)],
        metadatas=[
            {'asset_id': str(i), 'modality': 'images', 'species_id': 'lynx_pardinus'}
            for i in range(70)
        ],
    )
    service = SearchService(path, client=store.client, config=cfg, encoders=object())
    original = collection.query
    calls = []

    def observed(**kwargs):
        calls.append(kwargs['n_results'])
        return original(**kwargs)

    monkeypatch.setattr(collection, 'query', observed)
    monkeypatch.setattr(service, 'collection', lambda space: collection)
    rows = service.query_vector([1.0] + [0.0] * 511, 'images', limit=5)
    assert calls and len(rows) == 5 and rows[0]['id'] == '0'


def test_federation_deduplicates_assets_without_comparing_cosine_scores(search):
    rows = search.text('ecology', mode='multimodal')
    assert len({r['asset_id'] for r in rows}) == len(rows)
    assert all(r['score_type'] == 'rrf' for r in rows)


@pytest.mark.parametrize('query', ['', ' ', None, 1, 'x' * 2001])
def test_invalid_text_queries_rejected(search, query):
    with pytest.raises(ValueError):
        search.text(query)


@pytest.mark.parametrize('limit', [0, -1, 51, True, '3'])
def test_invalid_limits_rejected(search, limit):
    with pytest.raises(ValueError):
        search.query_vector([1.0] + [0.0] * 383, 'text', limit=limit)


def test_original_index_path_is_protected():
    with pytest.raises(ValueError, match='protected'):
        SearchService('data/chromadb', client=object())


def test_missing_snapshot_does_not_create_database(tmp_path):
    target = tmp_path / 'missing'
    with pytest.raises(FileNotFoundError):
        SearchService(target)
    assert not target.exists()


def test_unknown_or_missing_record(search):
    with pytest.raises(ValueError):
        search.by_record('absent', 'images')
    with pytest.raises(ValueError):
        search.collection('other')


@pytest.mark.parametrize(
    'key',
    [
        '../.env',
        'images/../secret.jpg',
        'images/a/b/c.jpg',
        '/images/a/b.jpg',
        'images\\a\\b.jpg',
        '',
    ],
)
def test_media_reference_traversal_rejected(key):
    with pytest.raises(ValueError):
        validate_key(key)


def test_asset_grouping_and_fusion():
    rows = [
        {'asset_id': 'a', 'score': 0.9},
        {'asset_id': 'a', 'score': 0.8},
        {'asset_id': 'b', 'score': 0.7},
    ]
    assert len(collapse(rows, 2)) == 2
    result = fuse_rankings([rows, [{'asset_id': 'b', 'score': -0.9}]])
    assert result[0]['asset_id'] == 'b'


def test_generation_has_model_input_and_reference_provenance(search):
    data = describe(b'image', search, captioner=lambda *a, **kw: 'a lynx in a forest')
    assert data['caption'] and len(data['input_sha256']) == 64 and data['revision']
    assert {x['modality'] for x in data['references']} == {'images', 'text'}


def test_empty_generation_is_an_error(search):
    with pytest.raises(ValueError):
        describe(b'image', search, captioner=lambda *a, **kw: '')


def test_upload_validation():
    out = io.BytesIO()
    Image.new('RGB', (32, 32)).save(out, format='JPEG')
    assert (
        query_upload({'data': base64.b64encode(out.getvalue()).decode(), 'modality': 'images'})
        == out.getvalue()
    )
    with pytest.raises(ValueError):
        query_upload({'data': '!bad', 'modality': 'images'})


def test_task1_from_a_mixed_record_resolves_monmodal_identity(search):
    rows = search.by_record('images0', 'image_text', same_modality=True)
    assert rows and all(
        row['modality'] == 'images' and row['asset_id'] != 'images0' for row in rows
    )


def test_task2_from_a_monmodal_record_resolves_shared_identity(search):
    rows = search.by_record('images0', 'images', mixed=True)
    assert {row['modality'] for row in rows} == {'images', 'text'}
    assert all(row['asset_id'] != 'images0' for row in rows)


def test_diversification_prevents_text_dominance(search):
    rows = search.text('lynx', mode='image_text', limit=4)
    assert len([row for row in rows if row['modality'] == 'images']) == 2
    assert len([row for row in rows if row['modality'] == 'text']) == 2


def test_external_image_is_not_persisted(search):
    before = search.status()
    out = io.BytesIO()
    Image.new('RGB', (32, 32)).save(out, format='JPEG')
    assert search.media(out.getvalue(), 'images', mixed=False)
    assert {row['modality'] for row in search.media(out.getvalue(), 'images', mixed=True)} == {
        'images',
        'text',
    }
    assert search.status() == before


def test_external_audio_has_mixed_results_and_duration_limit(search):
    import soundfile as sf
    import numpy as np

    out = io.BytesIO()
    sf.write(out, np.sin(np.arange(3200) * 0.1), 32000, format='FLAC')
    assert {row['modality'] for row in search.media(out.getvalue(), 'audio', mixed=True)} == {
        'audio',
        'text',
    }
    out = io.BytesIO()
    sf.write(out, np.zeros(32000 * 31), 32000, format='FLAC')
    with pytest.raises(ValueError):
        search.media(out.getvalue(), 'audio')


@pytest.mark.e2e
def test_real_http_ui_api_errors_and_host_protection(search):
    server = ThreadingHTTPServer(
        ('127.0.0.1', 0), make_handler(search, lambda key: (b'media', 'image/jpeg'))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base) as response:
            assert 'EcoSentinel' in response.read().decode()
            assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
        with urlopen(base + '/api/status') as response:
            assert len(json.load(response)['collections']) == 5
        req = Request(
            base + '/api/search',
            data=json.dumps({'query': 'lynx', 'mode': 'image_text', 'limit': 6}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urlopen(req) as response:
            assert len(json.load(response)['results']) == 6
        for path, status in [('/.env', 404), ('/api/media?key=../.env', 400)]:
            with pytest.raises(HTTPError) as exc:
                urlopen(base + path)
            assert exc.value.code == status
        req = Request(
            base + '/api/search',
            data=b'{}',
            headers={'Content-Type': 'application/json', 'Origin': 'http://evil.example'},
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(req)
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
