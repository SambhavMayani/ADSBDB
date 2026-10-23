"""Validate and deduplicate Formatted JPEG images into Trusted Zone.

The pipeline keeps the original bytes, rejects only objective quality failures,
and records all non-destructive quality indicators in JSON manifests. Exact
and verified visual duplicates are represented by a single canonical object.

Usage:
    python trusted_zone/validate_images.py --dry-run --max-items 5
    python trusted_zone/validate_images.py
    python trusted_zone/validate_images.py --species lynx_pardinus
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import time
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import boto3
import numpy as np
import yaml
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from PIL import Image, ImageOps

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trusted_zone.quality.duplicate_index import DuplicateIndex
from trusted_zone.quality.image_quality import analyze, assess_watermark, has_tesseract, image_rejection

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
FORMATTED_BUCKET = os.getenv("ECOSENTINEL_FORMATTED_BUCKET", "formatted-zone")
TRUSTED_BUCKET = os.getenv("ECOSENTINEL_TRUSTED_BUCKET", "trusted-zone")
SOURCE_PREFIX = "images/"
POLICY_FILE = ROOT / "config" / "trusted_quality.yaml"


def s3_client():
    load_dotenv(ROOT / ".env")
    user, password = os.getenv("MINIO_ROOT_USER"), os.getenv("MINIO_ROOT_PASSWORD")
    if not user or not password:
        raise RuntimeError("MINIO_ROOT_USER and MINIO_ROOT_PASSWORD are required")
    return boto3.client(
        "s3", endpoint_url=os.getenv("S3_ENDPOINT_URL", os.getenv("MINIO_ENDPOINT", "http://localhost:9000")),
        aws_access_key_id=user, aws_secret_access_key=password,
    )


def load_policy(path: Path = POLICY_FILE) -> tuple[str, dict]:
    with path.open(encoding="utf-8") as stream:
        policy = yaml.safe_load(stream)
    if not isinstance(policy, dict) or "images" not in policy or not policy.get("version"):
        raise ValueError("Invalid Trusted quality policy")
    config = policy["images"]
    positive = ("max_file_mb", "max_megapixels", "min_width", "min_height", "phash_max_hamming", "duplicate_ssim_min", "watermark_advanced_max_items")
    if any(not isinstance(config.get(field), (int, float)) or config[field] <= 0 for field in positive):
        raise ValueError("Trusted image policy has missing or invalid thresholds")
    if config["phash_max_hamming"] > 6 or not 0 < config["duplicate_ssim_min"] <= 1:
        raise ValueError("Only pHash distance <= 6 is indexed reliably")
    return str(policy["version"]), config


def ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)


def iter_sources(client, species: str | None = None):
    prefix = SOURCE_PREFIX + (species + "/" if species else "")
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=FORMATTED_BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            if not item["Key"].endswith("/"):
                yield item["Key"]


def head_optional(client, bucket: str, key: str):
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NotFound", "NoSuchKey"}:
            return None
        raise


def get_object(client, bucket: str, key: str) -> tuple[bytes, dict]:
    response = client.get_object(Bucket=bucket, Key=key)
    try:
        return response["Body"].read(), response.get("Metadata", {})
    finally:
        response["Body"].close()


def put_verified(client, bucket: str, key: str, body: bytes, content_type: str, metadata: dict) -> None:
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentLength=len(body), ContentType=content_type, Metadata=metadata)
    stored = client.head_object(Bucket=bucket, Key=key)
    if stored.get("ContentLength") != len(body):
        raise RuntimeError(f"Unverified write: {bucket}/{key}")


def safe_identity(key: str, metadata: dict) -> str:
    path = PurePosixPath(key)
    if len(path.parts) != 3 or path.parts[0] != "images" or path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("invalid_formatted_path")
    species = path.parts[1]
    if metadata.get("species_id") != species or metadata.get("modality") not in {"images", "image"}:
        raise ValueError("species_or_modality_mismatch")
    encoded = metadata.get("source_persistent_key_encoded")
    if not encoded or not unquote(encoded).startswith(f"persistent_landing/images/{species}/"):
        raise ValueError("invalid_source_lineage")
    return species


def watermark_on_bytes(data: bytes, method: str, config: dict) -> dict:
    with Image.open(io.BytesIO(data)) as img:
        rgb = ImageOps.exif_transpose(img).convert("RGB")
        rgb.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        pixels = np.asarray(rgb)
    return assess_watermark(pixels, method, config)


def status_manifest(key: str, version: str, source_meta: dict, source_etag: str | None, status: str, reason: str | None, metrics: dict, watermark: dict, duplicate: dict | None, seconds: float) -> dict:
    return {
        "source_key": key,
        "species_id": PurePosixPath(key).parts[1] if len(PurePosixPath(key).parts) > 1 else "unknown",
        "source_name": source_meta.get("source_name", "unknown"),
        "source_etag": source_etag,
        "policy_version": version,
        "status": status,
        "reason": reason,
        "metrics": metrics,
        "watermark": watermark,
        "duplicate": duplicate,
        "processing_seconds": round(seconds, 4),
        "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def run(client, config: dict, version: str, *, species: str | None = None, max_items: int | None = None, dry_run: bool = False, report: bool = True) -> dict:
    """Evaluate one deterministic batch; emit source-aligned quality manifests."""
    sources = sorted(iter_sources(client, species))
    if max_items is not None:
        sources = sources[:max_items]
    method = "advanced" if len(sources) <= config["watermark_advanced_max_items"] and has_tesseract() else "lightweight"
    stats = Counter()
    LOGGER.info("Images=%s; watermark method=%s", len(sources), method)
    if not dry_run:
        ensure_bucket(client, TRUSTED_BUCKET)

    with tempfile.TemporaryDirectory(prefix="ecosentinel_duplicates_") as temp:
        with DuplicateIndex(Path(temp) / "index.sqlite", config) as index:
            for key in sources:
                start = time.perf_counter()
                stats["processed"] += 1
                metrics: dict = {}
                watermark: dict = {"method": "not_assessed", "status": "not_assessed"}
                duplicate = None
                reason = None
                operational_error = False
                sha = None
                source_meta = {}
                etag = None
                try:
                    src_head = client.head_object(Bucket=FORMATTED_BUCKET, Key=key)
                    source_meta = src_head.get("Metadata", {})
                    etag = str(src_head.get("ETag", "")).strip('"')
                    species_id = safe_identity(key, source_meta)
                    size = int(src_head.get("ContentLength", 0))
                    metrics["size_mb"] = round(size / 1_000_000, 4)
                    if size <= 0:
                        raise ValueError("empty_file")
                    if size > config["max_file_mb"] * 1_000_000:
                        raise ValueError("file_size_limit_exceeded")
                    payload, _ = get_object(client, FORMATTED_BUCKET, key)
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", Image.DecompressionBombWarning)
                        metrics, features = analyze(payload, config)
                    reason = image_rejection(metrics, config)
                    sha = hashlib.sha256(payload).hexdigest()
                    metrics["sha256"] = sha
                    watermark = watermark_on_bytes(payload, method, config)
                    if watermark["status"] == "possible":
                        metrics["flags"].append("possible_watermark")
                    if reason is None:
                        duplicate = index.find(key, species_id, sha, features)
                        if duplicate:
                            reason = "cross_species_duplicate" if duplicate["cross_species"] else "visual_duplicate"
                        else:
                            index.add(key, species_id, sha, features)
                except (ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
                    reason = str(exc) if isinstance(exc, ValueError) else f"invalid_or_oversized_image:{type(exc).__name__}"
                    stats["quality_failures"] += 1
                    LOGGER.info("Quality rejection %s: %s", key, reason)
                except (ClientError, OSError) as exc:
                    reason = f"processing_error:{type(exc).__name__}"
                    operational_error = True
                    stats["errors"] += 1
                    LOGGER.error("Processing failure %s: %s", key, exc)

                status = "error" if operational_error else ("rejected" if reason else "accepted")
                stats[status] += 1
                elapsed = time.perf_counter() - start
                manifest = status_manifest(key, version, source_meta, etag, status, reason, metrics, watermark, duplicate, elapsed)
                if dry_run:
                    LOGGER.info("PLAN  %-8s %s%s", status, key, f" ({reason})" if reason else "")
                    continue

                manifest_key = f"_quality/images/{key.removeprefix(SOURCE_PREFIX).rsplit('.', 1)[0]}.json"
                raw_manifest = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                existing_manifest = head_optional(client, TRUSTED_BUCKET, manifest_key)
                if existing_manifest:
                    old_bytes, _ = get_object(client, TRUSTED_BUCKET, manifest_key)
                    old = json.loads(old_bytes)
                    if (old.get("status") == status and old.get("reason") == reason and old.get("source_etag") == etag
                            and old.get("policy_version") == version and old.get("duplicate") == duplicate):
                        stats["unchanged_manifests"] += 1
                    else:
                        put_verified(client, TRUSTED_BUCKET, manifest_key, raw_manifest, "application/json", {})
                else:
                    put_verified(client, TRUSTED_BUCKET, manifest_key, raw_manifest, "application/json", {})
                existing_trusted = head_optional(client, TRUSTED_BUCKET, key)
                if status == "accepted":
                    if existing_trusted and (existing_trusted.get("Metadata", {}).get("trusted_policy_version") == version
                                             and existing_trusted.get("Metadata", {}).get("source_formatted_sha256") == sha):
                        stats["unchanged_objects"] += 1
                    else:
                        if sha is None:
                            raise RuntimeError(f"Internal error: accepted with no hash: {key}")
                        metadata = dict(source_meta)
                        metadata.update({
                            "source_formatted_key_encoded": quote(key, safe=""),
                            "source_formatted_sha256": sha,
                            "trusted_policy_version": version,
                            "quality_status": "accepted",
                        })
                        put_verified(client, TRUSTED_BUCKET, key, payload, "image/jpeg", metadata)
                        stats["uploaded"] += 1
                elif existing_trusted:
                    # Preserve validated bytes; record proposed retirement for review.
                    stats["retirement_candidates"] += 1
                LOGGER.info("%-8s %s%s", status.upper(), key, f" ({reason})" if reason else "")

    if report and not dry_run and species is None and max_items is None:
        from trusted_zone.reporting.generate_image_report import generate
        location = generate(client, version, config)
        LOGGER.info("Quality report: %s", location)
    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species", help="Process one species (useful for smoke tests)")
    parser.add_argument("--max-items", type=int, help="Limit the batch size")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to MinIO")
    parser.add_argument("--no-report", action="store_true", help="Skip HTML report generation")
    args = parser.parse_args()
    if args.max_items is not None and args.max_items < 1:
        parser.error("--max-items must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    version, config = load_policy()
    stats = run(s3_client(), config, version, species=args.species, max_items=args.max_items, dry_run=args.dry_run, report=not args.no_report)
    print("\nTrusted Images summary")
    for name in ("processed", "accepted", "rejected", "uploaded", "unchanged_objects", "quality_failures", "errors"):
        print(f"{name:<20}: {stats.get(name, 0)}")
    return 1 if stats.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
