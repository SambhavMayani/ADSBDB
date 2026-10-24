"""Read-only inventories and byte-for-byte snapshots; never instantiate Chroma on the source."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


def inventory(path: Path) -> dict:
    path = Path(path).resolve()
    if not (path / 'chroma.sqlite3').is_file():
        raise ValueError('Expected an existing Chroma directory')
    result = {}
    for file in sorted(path.rglob('*')):
        if file.is_file():
            digest = hashlib.sha256()
            with file.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            result[file.relative_to(path).as_posix()] = {
                'bytes': file.stat().st_size,
                'sha256': digest.hexdigest(),
            }
    return result


def counts(path: Path) -> dict:
    """SQLite mode=ro avoids startup migrations and HNSW writes in the source."""
    uri = (Path(path).resolve() / 'chroma.sqlite3').as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as connection:
        return dict(
            connection.execute("""SELECT c.name, count(e.id) FROM collections c
            JOIN segments s ON s.collection=c.id LEFT JOIN embeddings e ON e.segment_id=s.id
            GROUP BY c.name""").fetchall()
        )


def snapshot(source: Path, target: Path) -> dict:
    """Caller must stop other writers first. Detect changes during copy; refuse reuse."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if target == source or source in target.parents or target in source.parents:
        raise ValueError('Snapshot destination must be separate from the source')
    if target.exists():
        raise FileExistsError('Refuse to overwrite an existing snapshot')
    before = inventory(source)
    shutil.copytree(source, target)
    if before != inventory(source) or before != inventory(target):
        raise RuntimeError('Source changed during snapshot; stop writers and use a new destination')
    return {'counts': counts(target), 'files': before}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('data/chromadb'))
    parser.add_argument('--snapshot', type=Path)
    args = parser.parse_args(argv)
    result = (
        snapshot(args.source, args.snapshot)
        if args.snapshot
        else {'counts': counts(args.source), 'files': inventory(args.source)}
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
