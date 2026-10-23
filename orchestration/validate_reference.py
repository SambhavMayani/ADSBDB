"""Evidence on the existing corpus: original index read-only, searches on a copy.

This is an explicit acceptance check, not a portable unit test. It requires the
local dataset, MinIO and the original cache. No existing embedding is generated.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import platform
import time

from exploitation_zone.contracts import ROOT
from exploitation_zone.indexer import execute, load_config
from exploitation_zone.source import TrustedRepository, create_minio_client
from exploitation_zone.vector_store import VectorStore
from orchestration.audit import inventory, snapshot
from orchestration.reconcile import reconcile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', action='store_true', help='Test real CPU encoders using the existing cache')
    parser.add_argument('--task3', action='store_true')
    parser.add_argument('--allow-model-download', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/validation/reference.json')
    args = parser.parse_args(argv)
    started = time.perf_counter()
    cfg = load_config()
    original = ROOT / cfg['chroma_path']
    print('Verifying the original index and Trusted lineage...', flush=True)
    before = inventory(original)
    destination = ROOT / 'data/search_index'
    if not destination.exists(): snapshot(original, destination)
    repo = TrustedRepository(create_minio_client(), cfg['trusted_bucket'])
    report = {'python': platform.python_version(), 'platform': platform.platform(),
              'reconciliation': reconcile(repo, original, cfg), 'checks': []}
    if report['reconciliation']['problems']:
        raise RuntimeError('Original dataset reconciliation failed')
    from multimodal_tasks.search import SearchService
    service = SearchService(destination)
    for space in ('images', 'audio', 'text'):
        record = service.collection(space).get(limit=1, include=['metadatas'])
        result = service.by_record(record['ids'][0], space, limit=5)
        assert result and all(row['asset_id'] != record['metadatas'][0]['asset_id'] for row in result)
        report['checks'].append({'task': 1, 'space': space, 'results': len(result)})
    class NoInference:
        def __getattr__(self, name):
            raise AssertionError('Unnecessary model invocation: ' + name)
    print('Checking idempotency with model invocation forbidden...', flush=True)
    stats = execute(cfg, repo, vector_store=VectorStore(destination), encoders=NoInference())
    assert not stats.get('errors') and not stats.get('new_or_updated_vectors') and stats['unchanged_assets'] == report['reconciliation']['trusted_assets']
    report['idempotency'] = stats
    if args.models:
        for mode, query in [('text', 'Hábitat y comportamiento del lince ibérico'),
                            ('image_text', 'Iberian lynx in its natural habitat'),
                            ('audio_text', 'owl calling at night'),
                            ('multimodal', 'birds near a river')]:
            print('CPU query:', mode, flush=True)
            start = time.perf_counter()
            rows = service.text(query, mode=mode, limit=8)
            assert rows
            modalities = sorted({row['modality'] for row in rows})
            if mode in ('image_text', 'audio_text', 'multimodal'):
                assert len(modalities) >= 2
            report['checks'].append({'task': 1 if mode == 'text' else 2, 'space': mode,
                      'query': query, 'modalities': modalities, 'results': len(rows),
                      'duration_seconds': round(time.perf_counter() - start, 3),
                      'top_species': [row['species_id'] for row in rows]})
    if args.models:
        for modality in ('images', 'audio'):
            key = next(repo.list(modality))
            data = repo.get(key)
            if modality == 'audio':
                from io import BytesIO
                import soundfile as sf
                source = BytesIO(data)
                info = sf.info(source)
                signal, rate = sf.read(BytesIO(data), frames=min(info.frames, info.samplerate * 2))
                out = BytesIO()
                sf.write(out, signal, rate, format='FLAC', subtype='PCM_16')
                data = out.getvalue()
            for mixed in (False, True):
                print('CPU media query:', modality, 'mixed' if mixed else 'same', flush=True)
                rows = service.media(data, modality, mixed=mixed, limit=6)
                kinds = sorted({row['modality'] for row in rows})
                assert rows and (len(kinds) >= 2 if mixed else kinds == [modality])
                report['checks'].append({'task': 2 if mixed else 1, 'input': modality,
                                         'results': len(rows), 'modalities': kinds})
    if args.task3:
        from multimodal_tasks.generate import describe
        key = next(repo.list('images'))
        service.encoders.release_all()
        print('Task 3: CPU caption and reference retrieval...', flush=True)
        result = describe(repo.get(key), service, allow_download=args.allow_model_download)
        assert result['caption'] and result['references']
        report['task3'] = result
    report['original_index_unchanged'] = before == inventory(original)
    if not report['original_index_unchanged']:
        raise RuntimeError('Original Chroma files changed during acceptance validation')
    report['duration_seconds'] = round(time.perf_counter() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'task3'}, ensure_ascii=False, indent=2))
    if 'task3' in report:
        print('Task 3 caption:', report['task3']['caption'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
