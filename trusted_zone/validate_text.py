"""EcoSentinel Trusted Text: conservative UTF-8 validation and deduplication.

Keeps content, case, punctuation, languages and paragraphs; NFC and LF are
already enforced in Formatted. Similarity and possible PII are audit flags,
never automatic redactions or near-duplicate exclusions.

Run from repository root:
    python trusted_zone/validate_text.py --dry-run --max-items 3
    python trusted_zone/validate_text.py
    python trusted_zone/validate_text.py --species lynx_pardinus
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
    FORMATTED_BUCKET, TRUSTED_BUCKET, QualityFailure, check_bucket, client_from_env,
    load_policy, make_manifest, publish, read_object, source_keys, validate_numeric_policy,
    verify_lineage,
)
from trusted_zone.quality.text_quality import candidate_near_duplicate, normalize_text

LOGGER = logging.getLogger(__name__)


def validate_config(config: dict):
    validate_numeric_policy(config, {
        "max_file_mb": (0.001, None), "short_document_warning_words": (0, None),
        "alphanumeric_ratio_warning": (0, 1), "near_duplicate_shingle_words": (1, 12),
        "near_duplicate_min_shingles": (1, None), "near_duplicate_jaccard_warning": (0, 1),
    })
    for name in ("near_duplicate_shingle_words", "near_duplicate_min_shingles", "short_document_warning_words"):
        if not isinstance(config[name], int) or isinstance(config[name], bool):
            raise ValueError(f"Expected integer policy setting: {name}")


def run(client, config: dict, version: str, policy_sha: str, *, species: str | None = None,
        max_items: int | None = None, dry_run: bool = False, report: bool = True) -> dict:
    validate_config(config)
    check_bucket(client, FORMATTED_BUCKET)
    keys = source_keys(client, "text", species)
    if max_items is not None:
        keys = keys[:max_items]
    if not dry_run:
        check_bucket(client, TRUSTED_BUCKET, create=True)
    stats = Counter()
    seen: dict[tuple[str, str], str] = {}  # within-species canonical normalized SHA
    global_seen: dict[str, tuple[str, str]] = {}
    accepted: list[dict] = []  # candidate discovery only; O(n²), acceptable for 64 docs

    for key in keys:
        started = time.perf_counter()
        stats["processed"] += 1
        metadata, metrics, duplicate = {}, {}, None
        etag, source_sha, data, reason = "", None, None, None
        status = "accepted"
        try:
            head = client.head_object(Bucket=FORMATTED_BUCKET, Key=key)
            metadata = head.get("Metadata", {})
            etag = str(head.get("ETag", "")).strip('"')
            current_species = verify_lineage(key, metadata, "text", ".txt")
            size = int(head.get("ContentLength", 0))
            metrics["formatted_size_bytes"] = size
            if size <= 0:
                raise QualityFailure("empty_file")
            if size > config["max_file_mb"] * 1_000_000:
                raise QualityFailure("file_size_limit_exceeded")
            raw = read_object(client, FORMATTED_BUCKET, key)
            source_sha = hashlib.sha256(raw).hexdigest()
            data, metrics, shingles = normalize_text(raw, config)
            metrics["sha256"] = source_sha
            normalized_sha = metrics["normalized_content_sha256"]
            canonical = seen.get((current_species, normalized_sha))
            if canonical:
                status, reason = "rejected", "exact_normalized_text_duplicate"
                duplicate = {"canonical_key": canonical, "kind": "normalized_sha256", "cross_species": False}
            else:
                cross = global_seen.get(normalized_sha)
                if cross and cross[1] != current_species:
                    duplicate = {"canonical_key": cross[0], "kind": "normalized_sha256",
                                 "cross_species": True, "decision": "kept_for_review"}
                    metrics["flags"].append("identical_text_across_species")
                candidate = candidate_near_duplicate(shingles, accepted, key, current_species, config)
                if candidate:
                    metrics["flags"].append("possible_near_duplicate")
                    metrics["near_duplicate_candidate"] = candidate
                seen[(current_species, normalized_sha)] = key
                global_seen.setdefault(normalized_sha, (key, current_species))
                accepted.append({"key": key, "species": current_species, "shingles": shingles})
        except QualityFailure as exc:
            reason, status = str(exc), "rejected"
            stats["quality_failures"] += 1
        except (ClientError, OSError) as exc:
            reason, status = f"processing_error:{type(exc).__name__}", "error"
            stats["errors"] += 1
            LOGGER.exception("Text processing failed: %s", key)

        stats[status] += 1
        manifest = make_manifest(
            key=key, metadata=metadata, etag=etag, version=version, policy_hash=policy_sha,
            status=status, reason=reason, metrics=metrics, duplicate=duplicate,
            elapsed=time.perf_counter() - started, source_sha=source_sha,
        )
        if dry_run:
            LOGGER.info("PLAN %-8s %s%s", status, key, f" ({reason})" if reason else "")
            continue
        publish(client, key=key, modality="text", data=data if status == "accepted" else None,
                metadata=metadata, source_sha=source_sha, policy_version=version,
                policy_sha=policy_sha, status=status, manifest=manifest, dry_run=False, stats=stats)
        LOGGER.info("%-8s %s%s", status.upper(), key, f" ({reason})" if reason else "")

    if report and not dry_run and species is None and max_items is None:
        from trusted_zone.reporting.generate_modality_report import generate
        LOGGER.info("Text quality report: %s", generate(client, "text", version, config))
    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species")
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    if args.max_items is not None and args.max_items < 1:
        parser.error("--max-items must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    version, config, sha = load_policy("trusted_text_quality.yaml", "text")
    stats = run(client_from_env(), config, version, sha, species=args.species,
                max_items=args.max_items, dry_run=args.dry_run, report=not args.no_report)
    print("\nTrusted Text summary")
    for item in ("processed", "accepted", "rejected", "uploaded", "unchanged_objects", "quality_failures", "errors"):
        print(f"{item:<20}: {stats.get(item, 0)}")
    return 1 if stats.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
