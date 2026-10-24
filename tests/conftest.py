"""No internet in default tests. Loopback supports isolated HTTP/Chroma checks."""

import socket
import pytest


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch, request):
    if request.node.get_closest_marker('models'):
        return
    original = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple) and len(address) > 1 and address[1] in (9000, 9001):
            raise AssertionError('Production MinIO endpoints are forbidden in pytest')
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
            raise AssertionError('Unexpected external network in offline test')
        return original(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    monkeypatch.setenv('TRANSFORMERS_OFFLINE', '1')
    monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'False')
    monkeypatch.delenv('SECURITY_ALERT_WEBHOOK_URL', raising=False)


@pytest.fixture(scope='module')
def search(tmp_path_factory, request):
    from exploitation_zone.indexer import load_config
    from exploitation_zone.vector_store import DIMENSIONS
    from exploitation_zone.contracts import policy_fingerprint
    from multimodal_tasks.search import SearchService
    import chromadb
    from chromadb.config import Settings

    cfg = load_config()
    path = tmp_path_factory.mktemp('query') / 'index'
    client = chromadb.PersistentClient(
        path=str(path), settings=Settings(anonymized_telemetry=False)
    )
    for space, dim in DIMENSIONS.items():
        col = client.create_collection(
            cfg['collections'][space],
            embedding_function=None,
            # Materialize the real index even for three-record fixtures. The default
            # 100/1000 thresholds leave tiny segments only in the transient buffer.
            configuration={'hnsw': {'space': 'cosine', 'batch_size': 2, 'sync_threshold': 2}},
            metadata={
                'contract_sha256': policy_fingerprint(cfg, '', space),
                'dimension': dim,
                'distance': 'cosine',
            },
        )
        kinds = (
            ['images', 'text']
            if space == 'image_text'
            else ['audio', 'text']
            if space == 'audio_text'
            else [space]
        )
        ids, vectors, mds, docs = [], [], [], []
        for kind in kinds:
            for i in range(3):
                ids.append(f'{kind}{i}')
                vectors.append([1.0, i * 0.1] + [0.0] * (dim - 2))
                mds.append(
                    {
                        'asset_id': kind + str(i),
                        'modality': kind,
                        'species_id': 'lynx_pardinus' if i < 2 else 'bubo_bubo',
                        'source_key': f'{kind}/lynx_pardinus/{i}.txt',
                        'source_name': 'test',
                    }
                )
                docs.append(getattr(request, 'param', {}).get('passage', 'fauna ecology ' + str(i)))
        col.add(ids=ids, embeddings=vectors, metadatas=mds, documents=docs)

    class Encoders:
        def release_all(self):
            pass

        def clip_image(self, data):
            return [1.0] + [0.0] * 511

        def clap_audio(self, data):
            return [1.0] + [0.0] * 511

        def clip_text(self, texts):
            return [[1.0] + [0.0] * 511]

        def clap_text(self, texts):
            return [[1.0] + [0.0] * 511]

        def sentence_transformer(self, key):
            class Model:
                def encode(self, text, **kw):
                    assert text.startswith('query: ')
                    return [1.0] + [0.0] * 383

            return Model()

    try:
        yield SearchService(path, client=client, encoders=Encoders())
    finally:
        # Chroma 1.5.9 has no public close; release owned native handles on Windows.
        client._system.stop()
