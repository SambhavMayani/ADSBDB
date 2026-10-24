"""SQLite-backed candidate index for exact and near-duplicate images.

Eight 8-bit bands of a 64-bit perceptual hash guarantee at least one matching
band whenever the Hamming distance is at most six. The candidates are then
verified with stronger structural and color comparisons. This avoids an
all-pairs O(n²) search while keeping thumbnails off Python's heap.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import cv2
import numpy as np

from .image_quality import ImageFeatures, confirm_duplicate, phash_distance


class DuplicateIndex:
    def __init__(self, db_path: Path, config: dict):
        self.config = config
        self.connection = sqlite3.connect(db_path)
        self.connection.executescript("""
            CREATE TABLE originals (
                object_key TEXT PRIMARY KEY,
                species_id TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                phash TEXT NOT NULL,
                preview BLOB NOT NULL
            );
            CREATE INDEX idx_originals_sha ON originals(sha256);
            CREATE TABLE bands (
                band_no INTEGER NOT NULL,
                band_value INTEGER NOT NULL,
                object_key TEXT NOT NULL
            );
            CREATE INDEX idx_bands_lookup ON bands(band_no, band_value);
        """)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.connection.close()

    @staticmethod
    def _preview(features: ImageFeatures) -> bytes:
        rgb_bgr = cv2.cvtColor(features.color, cv2.COLOR_RGB2BGR)
        success, encoded = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not success:
            raise ValueError('Cannot encode comparison thumbnail')
        return encoded.tobytes()

    @staticmethod
    def _restore(data: bytes, phash: int) -> ImageFeatures:
        encoded = np.frombuffer(data, dtype=np.uint8)
        image_bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise ValueError('Damaged fingerprint thumbnail')
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return ImageFeatures(phash, grey, rgb)

    def find(self, key: str, species: str, sha: str, features: ImageFeatures) -> dict | None:
        """Return a verified canonical match, or None if content is distinct."""
        exact = self.connection.execute(
            'SELECT object_key, species_id FROM originals WHERE sha256=? LIMIT 1', (sha,)
        ).fetchone()
        if exact:
            return {
                'canonical_key': exact[0],
                'cross_species': exact[1] != species,
                'method': 'sha256',
                'similarity': 1.0,
            }

        bands = [(i, (features.phash >> (8 * i)) & 255) for i in range(8)]
        where = ' OR '.join(['(b.band_no=? AND b.band_value=?)'] * 8)
        values = [part for pair in bands for part in pair]
        candidates = self.connection.execute(
            f'SELECT DISTINCT o.object_key,o.species_id,o.phash,o.preview '
            f'FROM bands b JOIN originals o ON b.object_key=o.object_key '
            f'WHERE {where} ORDER BY o.object_key',
            values,
        )
        for candidate_key, candidate_species, hex_hash, thumbnail in candidates:
            candidate_hash = int(hex_hash, 16)
            if phash_distance(features.phash, candidate_hash) > self.config['phash_max_hamming']:
                continue
            current = self._restore(self._preview(features), features.phash)
            reference = self._restore(thumbnail, candidate_hash)
            match, ssim, color_dist = confirm_duplicate(current, reference, self.config)
            if match:
                return {
                    'canonical_key': candidate_key,
                    'cross_species': candidate_species != species,
                    'method': 'phash_ssim_color',
                    'similarity': ssim,
                    'color_distance': color_dist,
                }
        return None

    def add(self, key: str, species: str, sha: str, features: ImageFeatures) -> None:
        with self.connection:
            self.connection.execute(
                'INSERT INTO originals VALUES (?,?,?,?,?)',
                (key, species, sha, f'{features.phash:016x}', self._preview(features)),
            )
            self.connection.executemany(
                'INSERT INTO bands VALUES (?,?,?)',
                [(i, (features.phash >> (8 * i)) & 255, key) for i in range(8)],
            )
