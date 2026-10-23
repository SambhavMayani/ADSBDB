"""Shared MinIO/lineage/idempotence primitives for Trusted Audio and Text.

Keep this module separate from validate_images.py: existing Trusted Images stays
unchanged. Nothing here writes to the Formatted or Landing buckets.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import boto3
import yaml
from botocore.exceptions import ClientError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
FORMATTED_BUCKET = os.getenv("ECOSENTINEL_FORMATTED_BUCKET", "formatted-zone")
TRUSTED_BUCKET = os.getenv("ECOSENTINEL_TRUSTED_BUCKET", "trusted-zone")


class QualityFailure(ValueError):
    """Deterministic rejection of an invalid or inconsistent source asset."""


def client_from_env():
    load_dotenv(ROOT / ".env")
    user = os.getenv("MINIO_ROOT_USER")
    password = os.getenv("MINIO_ROOT_PASSWORD")
    if not user or not password:
        raise RuntimeError("MINIO_ROOT_USER and MINIO_ROOT_PASSWORD are required in .env")
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL", os.getenv("MINIO_ENDPOINT", "http://localhost:9000")),
        aws_access_key_id=user,
        aws_secret_access_key=password,
    )


def load_policy(name: str, section: str) -> tuple[str, dict, str]:
    with (ROOT / "config" / name).open(encoding="utf-8") as stream:
        policy = yaml.safe_load(stream)
    if not isinstance(policy, dict) or not policy.get("version") or not isinstance(policy.get(section), dict):
        raise ValueError(f"Invalid quality policy: {name}")
    settings = policy[section]
    fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True).encode("utf-8")).hexdigest()
    return str(policy["version"]), settings, fingerprint


def check_bucket(client, bucket: str, *, create: bool = False):
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if create and exc.response.get("Error", {}).get("Code") in {"404", "NoSuchBucket", "NotFound"}:
            client.create_bucket(Bucket=bucket)
        else:
            raise


def source_keys(client, modality: str, species: str | None = None) -> list[str]:
    prefix = modality + "/" + (species + "/" if species else "")
    found = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=FORMATTED_BUCKET, Prefix=prefix):
        found.extend(obj["Key"] for obj in page.get("Contents", []) if not obj["Key"].endswith("/"))
    return sorted(found)


def verify_lineage(key: str, metadata: dict, modality: str, extension: str) -> str:
    path = PurePosixPath(key)
    if len(path.parts) != 3 or path.parts[0] != modality or path.suffix.lower() != extension:
        raise QualityFailure("invalid_formatted_path_or_extension")
    species = path.parts[1]
    if metadata.get("species_id") != species or metadata.get("modality") != modality:
        raise QualityFailure("species_or_modality_mismatch")
    if not metadata.get("source_name") or metadata["source_name"] == "unknown":
        raise QualityFailure("missing_source_name")
    encoded = metadata.get("source_persistent_key_encoded", "")
    decoded = unquote(encoded)
    if not encoded or not decoded.startswith(f"persistent_landing/{modality}/{species}/"):
        raise QualityFailure("invalid_source_lineage")
    return species


def object_head(client, bucket: str, key: str):
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NotFound", "NoSuchKey"}:
            return None
        raise


def read_object(client, bucket: str, key: str) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    try:
        return response["Body"].read()
    finally:
        response["Body"].close()


def put_checked(client, key: str, data: bytes, content_type: str, metadata: dict):
    client.put_object(
        Bucket=TRUSTED_BUCKET, Key=key, Body=data, ContentLength=len(data),
        ContentType=content_type, Metadata=metadata,
    )
    stored = client.head_object(Bucket=TRUSTED_BUCKET, Key=key)
    if stored.get("ContentLength") != len(data):
        raise RuntimeError(f"Unverified MinIO write: {key}")


def manifest_key(key: str, modality: str) -> str:
    relative = PurePosixPath(key).relative_to(modality).with_suffix(".json")
    return f"_quality/{modality}/{relative.as_posix()}"


def make_manifest(*, key: str, metadata: dict, etag: str, version: str, policy_hash: str,
                  status: str, reason: str | None, metrics: dict, duplicate: dict | None,
                  elapsed: float, source_sha: str | None) -> dict:
    row = {
        "source_key": key,
        "species_id": PurePosixPath(key).parts[1],
        "source_name": metadata.get("source_name", "unknown"),
        "source_etag": etag,
        "source_sha256": source_sha,
        "policy_version": version,
        "policy_sha256": policy_hash,
        "status": status,
        "reason": reason,
        "metrics": metrics,
        "duplicate": duplicate,
    }
    row["content_fingerprint"] = hashlib.sha256(
        json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    row["processing_seconds"] = round(elapsed, 4)
    row["analyzed_at_utc"] = datetime.now(timezone.utc).isoformat()
    return row


def publish(client, *, key: str, modality: str, data: bytes | None, metadata: dict,
            source_sha: str | None, policy_version: str, policy_sha: str,
            status: str, manifest: dict, dry_run: bool, stats: dict):
    """Publish status + canonical object; safe to repeat with unchanged content.

    On unexpected processing errors we do not delete previously accepted data,
    which avoids destructive actions during temporary MinIO/network failures.
    """
    if dry_run:
        return
    json_key = manifest_key(key, modality)
    old = object_head(client, TRUSTED_BUCKET, json_key)
    if old:
        try:
            old_manifest = json.loads(read_object(client, TRUSTED_BUCKET, json_key))
        except (ValueError, UnicodeDecodeError):
            old_manifest = {}
        if old_manifest.get("content_fingerprint") == manifest["content_fingerprint"]:
            stats["unchanged_manifests"] += 1
        else:
            encoded = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
            put_checked(client, json_key, encoded, "application/json", {})
    else:
        encoded = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        put_checked(client, json_key, encoded, "application/json", {})

    old_trusted = object_head(client, TRUSTED_BUCKET, key)
    if status == "accepted":
        if data is None or source_sha is None:
            raise RuntimeError(f"Accepted without output for {key}")
        if old_trusted:
            old_meta = old_trusted.get("Metadata", {})
            if (old_meta.get("source_formatted_sha256") == source_sha
                and old_meta.get("trusted_policy_version") == policy_version
                and old_meta.get("trusted_policy_sha256") == policy_sha):
                stats["unchanged_objects"] += 1
                return
        new_metadata = dict(metadata)
        new_metadata.update({
            "source_formatted_key_encoded": quote(key, safe=""),
            "source_formatted_sha256": source_sha,
            "trusted_policy_version": policy_version,
            "trusted_policy_sha256": policy_sha,
            "quality_status": "accepted",
        })
        put_checked(client, key, data, "audio/flac" if modality == "audio" else "text/plain; charset=utf-8", new_metadata)
        stats["uploaded"] += 1
    elif status == "rejected" and old_trusted:
        # Accepted historical data is retained; the quality manifest records rejection.
        stats["retirement_candidates"] += 1


def validate_numeric_policy(config: dict, rules: dict[str, tuple[float, float | None]]) -> None:
    for key, (minimum, maximum) in rules.items():
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"Invalid quality policy threshold: {key}")
