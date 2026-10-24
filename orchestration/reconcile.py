"""Read-only reconciliation of accepted Trusted assets and persisted vector parts."""

from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from exploitation_zone.contracts import ROOT
from exploitation_zone.indexer import SPACES, load_config
from exploitation_zone.source import TrustedRepository
from orchestration.storage import create_client


def reconcile(repository, index: Path, cfg: dict, *, check_bytes=True):
    assets = {}
    for modality in SPACES:
        for key in repository.list(modality):
            repository.source_info(key)
            assets[key] = (
                modality,
                hashlib.sha256(repository.get(key)).hexdigest() if check_bytes else None,
            )
    if not assets:
        raise ValueError('No accepted Trusted assets; refusing a successful empty pipeline')
    dbfile = Path(index).resolve() / 'chroma.sqlite3'
    if not dbfile.is_file():
        raise FileNotFoundError('No existing Chroma database to reconcile')
    problems, totals = [], Counter()
    with sqlite3.connect(dbfile.as_uri() + '?mode=ro', uri=True) as db:
        for space, name in cfg['collections'].items():
            grouped = defaultdict(dict)
            query = """SELECT e.embedding_id,m.key,m.string_value,m.int_value FROM collections c
                JOIN segments s ON s.collection=c.id JOIN embeddings e ON e.segment_id=s.id
                JOIN embedding_metadata m ON m.id=e.id WHERE c.name=?"""
            for rid, key, string, integer in db.execute(query, (name,)):
                grouped[rid][key] = string if string is not None else integer
            by_asset = defaultdict(list)
            for rid, md in grouped.items():
                by_asset[md.get('source_key')].append(md)
            expected_keys = {
                key for key, (modality, _) in assets.items() if space in SPACES[modality]
            }
            for key in expected_keys - by_asset.keys():
                problems.append(f'{space}: missing asset {key}')
            for key in by_asset.keys() - expected_keys:
                problems.append(f'{space}: stale or unaccepted asset {key}')
            for key in expected_keys & by_asset.keys():
                parts = by_asset[key]
                if any(md.get('expected_parts') != len(parts) for md in parts) or {
                    md.get('part') for md in parts
                } != set(range(len(parts))):
                    problems.append(f'{space}: incomplete parts {key}')
                if check_bytes and any(md.get('source_sha256') != assets[key][1] for md in parts):
                    problems.append(f'{space}: source checksum mismatch {key}')
            totals[space] = len(grouped)
    return {
        'status': 'failed' if problems else 'completed',
        'trusted_assets': len(assets),
        'trusted_by_modality': dict(Counter(m for m, _ in assets.values())),
        'collections': dict(totals),
        'total_vectors': sum(totals.values()),
        'problems': problems,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--index', type=Path)
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    bucket = os.getenv('ECOSENTINEL_TRUSTED_BUCKET', cfg['trusted_bucket'])
    index = args.index or Path(os.getenv('ECOSENTINEL_CHROMA_PATH', str(ROOT / cfg['chroma_path'])))
    result = reconcile(TrustedRepository(create_client(), bucket), index, cfg)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result['problems'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
