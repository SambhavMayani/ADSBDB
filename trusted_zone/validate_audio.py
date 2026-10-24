"""EcoSentinel Trusted Audio: validate FLAC PCM16, profile, deduplicate, audit.

No trimming, downmixing, filtering, resampling, denoising or normalization.
Accepted FLAC bytes remain bit-for-bit identical to Formatted Zone.

Run from repository root:
    python trusted_zone/validate_audio.py --dry-run --max-items 3
    python trusted_zone/validate_audio.py
    python trusted_zone/validate_audio.py --species lynx_pardinus
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trusted_zone.pipeline_common import (
    FORMATTED_BUCKET,
    TRUSTED_BUCKET,
    QualityFailure,
    check_bucket,
    client_from_env,
    load_policy,
    make_manifest,
    publish,
    read_object,
    source_keys,
    validate_numeric_policy,
    verify_lineage,
)
from trusted_zone.quality.audio_quality import audio_metrics

LOGGER = logging.getLogger(__name__)


def validate_config(config: dict):
    validate_numeric_policy(
        config,
        {
            'max_file_mb': (0.001, None),
            'min_duration_seconds': (0.0, None),
            'short_duration_warning_seconds': (0.0, None),
            'clipping_amplitude_threshold': (0.01, 1),
            'clipping_pct_warning': (0, 100),
            'low_rms_dbfs_warning': (-150, 0),
            'low_energy_dbfs_threshold': (-150, 0),
            'low_energy_window_pct_warning': (0, 100),
            'dc_offset_warning': (0, 1),
        },
    )


def run(
    client,
    config: dict,
    version: str,
    policy_sha: str,
    *,
    species: str | None = None,
    max_items: int | None = None,
    dry_run: bool = False,
    report: bool = True,
) -> dict:
    validate_config(config)
    check_bucket(client, FORMATTED_BUCKET)
    keys = source_keys(client, 'audio', species)
    if max_items is not None:
        keys = keys[:max_items]
    if not dry_run:
        check_bucket(client, TRUSTED_BUCKET, create=True)
    stats = Counter()
    seen: dict[tuple[str, str], str] = {}  # (species, hash) -> canonical key
    global_pcm: dict[str, tuple[str, str]] = {}  # PCM -> (first key, species)

    for key in keys:
        started = time.perf_counter()
        stats['processed'] += 1
        metadata, metrics, duplicate = {}, {}, None
        etag, source_sha, data, reason = '', None, None, None
        status = 'accepted'
        try:
            head = client.head_object(Bucket=FORMATTED_BUCKET, Key=key)
            metadata = head.get('Metadata', {})
            etag = str(head.get('ETag', '')).strip('"')
            current_species = verify_lineage(key, metadata, 'audio', '.flac')
            size = int(head.get('ContentLength', 0))
            metrics['file_size_mb'] = round(size / 1_000_000, 5)
            if size <= 0:
                raise QualityFailure('empty_file')
            if size > config['max_file_mb'] * 1_000_000:
                raise QualityFailure('file_size_limit_exceeded')
            data = read_object(client, FORMATTED_BUCKET, key)
            source_sha = hashlib.sha256(data).hexdigest()
            metrics = audio_metrics(data, config)
            metrics['sha256'] = source_sha
            pcm_sha = metrics['decoded_pcm_sha256']
            canonical = seen.get((current_species, 'raw:' + source_sha))
            kind = 'exact_byte_duplicate'
            if not canonical:
                canonical = seen.get((current_species, 'pcm:' + pcm_sha))
                kind = 'identical_decoded_pcm_duplicate'
            if canonical:
                reason = kind
                duplicate = {'canonical_key': canonical, 'kind': kind, 'cross_species': False}
                status = 'rejected'
            else:
                cross = global_pcm.get(pcm_sha)
                if cross and cross[1] != current_species:
                    # Species conflict cannot be resolved without domain review.
                    duplicate = {
                        'canonical_key': cross[0],
                        'kind': 'identical_decoded_pcm',
                        'cross_species': True,
                        'decision': 'kept_for_review',
                    }
                    metrics['flags'].append('identical_audio_across_species')
                seen[(current_species, 'raw:' + source_sha)] = key
                seen[(current_species, 'pcm:' + pcm_sha)] = key
                global_pcm.setdefault(pcm_sha, (key, current_species))
        except QualityFailure as exc:
            reason, status = str(exc), 'rejected'
            stats['quality_failures'] += 1
        except (ClientError, OSError) as exc:
            reason, status = f'processing_error:{type(exc).__name__}', 'error'
            stats['errors'] += 1
            LOGGER.exception('Audio processing failed: %s', key)

        stats[status] += 1
        manifest = make_manifest(
            key=key,
            metadata=metadata,
            etag=etag,
            version=version,
            policy_hash=policy_sha,
            status=status,
            reason=reason,
            metrics=metrics,
            duplicate=duplicate,
            elapsed=time.perf_counter() - started,
            source_sha=source_sha,
        )
        if dry_run:
            LOGGER.info('PLAN %-8s %s%s', status, key, f' ({reason})' if reason else '')
            continue
        publish(
            client,
            key=key,
            modality='audio',
            data=data if status == 'accepted' else None,
            metadata=metadata,
            source_sha=source_sha,
            policy_version=version,
            policy_sha=policy_sha,
            status=status,
            manifest=manifest,
            dry_run=False,
            stats=stats,
        )
        LOGGER.info('%-8s %s%s', status.upper(), key, f' ({reason})' if reason else '')

    if report and not dry_run and species is None and max_items is None:
        from trusted_zone.reporting.generate_modality_report import generate

        LOGGER.info('Audio quality report: %s', generate(client, 'audio', version, config))
    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--species')
    parser.add_argument('--max-items', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    if args.max_items is not None and args.max_items < 1:
        parser.error('--max-items must be positive')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    version, config, sha = load_policy('trusted_audio_quality.yaml', 'audio')
    stats = run(
        client_from_env(),
        config,
        version,
        sha,
        species=args.species,
        max_items=args.max_items,
        dry_run=args.dry_run,
        report=not args.no_report,
    )
    print('\nTrusted Audio summary')
    for item in (
        'processed',
        'accepted',
        'rejected',
        'uploaded',
        'unchanged_objects',
        'quality_failures',
        'errors',
    ):
        print(f'{item:<20}: {stats.get(item, 0)}')
    return 1 if stats.get('errors') else 0


if __name__ == '__main__':
    raise SystemExit(main())
