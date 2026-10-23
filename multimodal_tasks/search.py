"""Task 1 / Task 2: explicit embeddings, source grouping, filters and rank fusion.

CLIP, CLAP and E5 distances are never compared across vector spaces.
The original index cannot be opened by this service: use an audited snapshot.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import threading

from exploitation_zone.contracts import ROOT, policy_fingerprint
from exploitation_zone.encoders import Encoders, normalize_vector
from exploitation_zone.indexer import load_config
from exploitation_zone.segments import decode_audio, prepare_audio, split_audio
from exploitation_zone.vector_store import DIMENSIONS


def fuse_rankings(rankings: list[list[dict]], k: int = 60) -> list[dict]:
    """Reciprocal rank fusion aggregates at asset level, not chunk frequency."""
    scores, rows = defaultdict(float), {}
    for ranking in rankings:
        seen = set()
        for rank, row in enumerate(ranking, 1):
            asset = row['asset_id']
            if asset in seen:
                continue
            seen.add(asset)
            scores[asset] += 1 / (k + rank)
            rows.setdefault(asset, dict(row))
    return [dict(rows[asset], score=score, score_type='rrf')
            for asset, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def collapse(rows: list[dict], limit: int) -> list[dict]:
    seen, result = set(), []
    for row in rows:
        if row['asset_id'] not in seen:
            seen.add(row['asset_id'])
            result.append(row)
        if len(result) == limit:
            break
    return result


def diversify(rows, limit, kinds):
    """Visible modality quotas, preserving each modality's similarity order."""
    present = [kind for kind in kinds if any(row['modality'] == kind for row in rows)]
    if len(present) < 2 or limit < len(present):
        return rows[:limit]
    chosen = set()
    for i, kind in enumerate(present):
        quota = limit // len(present) + int(i < limit % len(present))
        chosen.update(row['asset_id'] for row in [r for r in rows if r['modality'] == kind][:quota])
    for row in rows:
        if len(chosen) >= limit:
            break
        chosen.add(row['asset_id'])
    return [row for row in rows if row['asset_id'] in chosen][:limit]


class SearchService:
    def __init__(self, path=None, *, config=None, client=None, encoders=None):
        self.cfg = config or load_config()
        self.path = Path(path or os.getenv('ECOSENTINEL_SEARCH_INDEX', str(ROOT / 'data/search_index'))).resolve()
        original = (ROOT / self.cfg['chroma_path']).resolve()
        if self.path == original or original in self.path.parents:
            raise ValueError('Use a snapshot; the original Chroma index is protected')
        if client is None:
            if not (self.path / 'chroma.sqlite3').is_file():
                raise FileNotFoundError('Create a search snapshot with python -m orchestration.audit --snapshot data/search_index')
            import chromadb
            from chromadb.config import Settings
            client = chromadb.PersistentClient(path=str(self.path), settings=Settings(anonymized_telemetry=False))
        self.client = client
        self.encoders = encoders or Encoders(self.cfg, device='cpu')
        self.lock = threading.Lock()

    def collection(self, space):
        if space not in DIMENSIONS:
            raise ValueError('Unknown embedding space')
        collection = self.client.get_collection(self.cfg['collections'][space], embedding_function=None)
        md = collection.metadata or {}
        if md.get('contract_sha256') != policy_fingerprint(self.cfg, '', space) or md.get('dimension') != DIMENSIONS[space] or md.get('distance') != 'cosine':
            raise ValueError('Incompatible retrieval/index contract')
        return collection

    def status(self):
        return {space: self.collection(space).count() for space in DIMENSIONS}

    def query_vector(self, vector, space, *, limit=8, species=None, modality=None, exclude_asset=None):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError('Limit must be between 1 and 50')
        col = self.collection(space)
        if not col.count():
            return []
        filters = []
        if species:
            filters.append({'species_id': species})
        if modality:
            if modality not in ('images', 'audio', 'text'):
                raise ValueError('Invalid modality')
            filters.append({'modality': modality})
        if exclude_asset:
            filters.append({'asset_id': {'$ne': exclude_asset}})
        kwargs = {'where': filters[0] if len(filters) == 1 else {'$and': filters}} if filters else {}
        # Grow the candidate pool until enough distinct assets are found.
        count = len(col.get(include=[], **kwargs)['ids']) if filters else col.count()
        if count == 0:
            return []
        query = normalize_vector(vector, DIMENSIONS[space])
        if count <= 64:
            # Tiny/new Chroma segments can lack an on-disk HNSW reader. An exact
            # scan is deterministic and bounded to 64 vectors, without masking
            # storage errors or rebuilding the index. Larger sets still use HNSW.
            import numpy as np
            data = col.get(include=['embeddings', 'metadatas', 'documents'], **kwargs)
            rows = []
            for rid, md, document, stored in zip(data['ids'], data['metadatas'], data['documents'], data['embeddings']):
                score = float(np.dot(query, normalize_vector(stored, DIMENSIONS[space])))
                rows.append({'id': rid, **md, 'snippet': document if md.get('modality') == 'text' else '',
                             'score': score, 'score_type': 'cosine', 'space': space})
            rows.sort(key=lambda row: (-row['score'], row['asset_id'], row['id']))
            return collapse(rows, limit)
        candidates = min(count, max(32, limit * 4))
        while True:
            data = col.query(query_embeddings=[query],
                             n_results=candidates, include=['metadatas', 'documents', 'distances'], **kwargs)
            rows = []
            for rid, md, document, distance in zip(data['ids'][0], data['metadatas'][0], data['documents'][0], data['distances'][0]):
                if not math.isfinite(float(distance)):
                    raise ValueError('Non-finite search distance')
                rows.append({'id': rid, **md, 'snippet': document if md.get('modality') == 'text' else '',
                             'score': 1 - float(distance), 'score_type': 'cosine', 'space': space})
            rows = collapse(rows, limit)
            if len(rows) >= limit or candidates == count:
                return rows
            candidates = min(count, candidates * 2)

    def text(self, query, *, mode='multimodal', limit=8, species=None, modality=None):
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError('Enter a query of 1–2000 characters')
        if mode not in ('text', 'image_text', 'audio_text', 'multimodal'):
            raise ValueError('Invalid search mode')
        spaces = ('text', 'image_text', 'audio_text') if mode == 'multimodal' else (mode,)
        rankings = []
        with self.lock:
            try:
                for space in spaces:
                    self.encoders.release_all()
                    if space == 'text':
                        model = self.encoders.sentence_transformer('text')
                        vector = model.encode('query: ' + query, normalize_embeddings=True, convert_to_numpy=True)
                    elif space == 'image_text':
                        vector = self.encoders.clip_text([query])[0]
                    else:
                        vector = self.encoders.clap_text([query])[0]
                    rankings.append(self.query_space(vector, space, limit=limit, species=species, modality=modality))
            finally:
                self.encoders.release_all()
        if len(rankings) > 1:
            return diversify(fuse_rankings(rankings), limit, ('images', 'audio', 'text')) if modality is None else fuse_rankings(rankings)[:limit]
        return rankings[0]

    def query_space(self, vector, space, *, limit=8, species=None, modality=None, exclude_asset=None):
        kinds = {'image_text': ('images', 'text'), 'audio_text': ('audio', 'text')}.get(space)
        if modality is not None or not kinds or limit < 2:
            return self.query_vector(vector, space, limit=limit, species=species, modality=modality, exclude_asset=exclude_asset)
        rows = []
        for kind in kinds:
            rows.extend(self.query_vector(vector, space, limit=limit, species=species,
                                          modality=kind, exclude_asset=exclude_asset))
        rows.sort(key=lambda row: (-row['score'], row['asset_id']))
        return diversify(rows, limit, kinds)

    def by_record(self, record, space, *, limit=8, species=None, modality=None, same_modality=False, mixed=False):
        col = self.collection(space)
        row = col.get(ids=[record], include=['embeddings', 'metadatas'])
        if not row['ids']:
            raise ValueError('Reference record not found')
        if same_modality or mixed:
            if same_modality and mixed:
                raise ValueError('Select same modality or mixed search')
            kind = row['metadatas'][0]['modality']
            space = kind if same_modality else ('audio_text' if kind == 'audio' else 'image_text')
            col = self.collection(space)
            # IDs are space-specific; resolve the same source through asset identity.
            row = col.get(where={'asset_id': row['metadatas'][0]['asset_id']}, limit=1,
                          include=['embeddings', 'metadatas'])
            if not row['ids']:
                raise ValueError('Reference asset is not available in the requested space')
        return self.query_space(row['embeddings'][0], space, limit=limit, species=species,
                                 modality=modality, exclude_asset=row['metadatas'][0]['asset_id'])

    def media(self, data, modality, *, mixed=False, limit=8, species=None):
        """External image/audio query; bytes live in memory, never indexed."""
        with self.lock:
            try:
                self.encoders.release_all()
                if modality == 'images':
                    space = 'image_text' if mixed else 'images'
                    return self.query_space(self.encoders.clip_image(data), space, limit=limit, species=species)
                if modality == 'audio':
                    import soundfile as sf
                    from io import BytesIO
                    info = sf.info(BytesIO(data))
                    if info.duration > 30 or info.channels > 8:
                        raise ValueError('Query audio is limited to 30 seconds / 8 channels')
                    signal, rate = decode_audio(data)
                    if len(signal) / rate > 30:
                        raise ValueError('Query audio is limited to 30 seconds')
                    mono = prepare_audio(signal, rate, 48000)
                    space = 'audio_text' if mixed else 'audio'
                    rankings = [self.query_space(self.encoders.clap_audio(part.signal), space,
                                                 limit=limit, species=species)
                                for part in split_audio(mono, 48000, 10)]
                    return fuse_rankings(rankings)[:limit]
                raise ValueError('Media query must be images or audio')
            finally:
                self.encoders.release_all()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path)
    parser.add_argument('--query')
    parser.add_argument('--record')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--modality', choices=['images', 'audio'])
    parser.add_argument('--mixed', action='store_true')
    parser.add_argument('--space', default='text', choices=list(DIMENSIONS) + ['multimodal'])
    parser.add_argument('--species')
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args(argv)
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    service = SearchService(args.index)
    if args.status:
        result = service.status()
    elif args.record:
        result = service.by_record(args.record, args.space, limit=args.limit, species=args.species)
    elif args.file and args.modality:
        if args.file.stat().st_size > 10 * 1024 * 1024:
            parser.error('Query upload exceeds 10 MB')
        result = service.media(args.file.read_bytes(), args.modality, mixed=args.mixed, limit=args.limit, species=args.species)
    elif args.query:
        result = service.text(args.query, mode=args.space, limit=args.limit, species=args.species)
    else:
        parser.error('Select --status, --query, --record or --file with --modality')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
