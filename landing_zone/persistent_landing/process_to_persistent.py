import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv


# ---------------------------------------------------------
# MinIO configuration
# ---------------------------------------------------------

BUCKET_NAME = "landing-zone"

TEMPORAL_PREFIX = "temporal_landing/"
PERSISTENT_PREFIX = "persistent_landing/"
CONTROL_COMPLETED_PREFIX = "_control/completed/"


# ---------------------------------------------------------
# MinIO connection
# ---------------------------------------------------------

load_dotenv()

minio_client = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id=os.getenv("MINIO_ROOT_USER"),
    aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD"),
)


# ---------------------------------------------------------
# Temporal Landing discovery
# ---------------------------------------------------------

def list_temporal_objects():
    """
    List every object currently stored in Temporal Landing.

    Pagination is used so that the code continues working
    when the number of objects grows.
    """

    paginator = minio_client.get_paginator(
        "list_objects_v2"
    )

    object_keys = []

    for page in paginator.paginate(
        Bucket=BUCKET_NAME,
        Prefix=TEMPORAL_PREFIX,
    ):
        for item in page.get("Contents", []):
            object_keys.append(
                item["Key"]
            )

    return sorted(object_keys)


# ---------------------------------------------------------
# Object information
# ---------------------------------------------------------

def get_object_info(object_key):
    """
    Retrieve metadata and technical information associated
    with one Temporal Landing object.
    """

    return minio_client.head_object(
        Bucket=BUCKET_NAME,
        Key=object_key,
    )


# ---------------------------------------------------------
# Object key parsing
# ---------------------------------------------------------

def parse_temporal_object_key(object_key):
    """
    Extract the asset hash and original filename from
    a Temporal Landing key.

    Expected format:

    temporal_landing/<hash>__<original_filename>
    """

    temporal_filename = object_key.removeprefix(
        TEMPORAL_PREFIX
    )

    if "__" not in temporal_filename:
        raise ValueError(
            f"Unexpected Temporal key format: {object_key}"
        )

    asset_hash, original_filename = (
        temporal_filename.split(
            "__",
            1,
        )
    )

    return asset_hash, original_filename


# ---------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------

def sanitize_component(value):
    """
    Convert metadata values into safe components for
    Persistent Landing object names.
    """

    value = value.strip().lower()

    return re.sub(
        r"[^a-z0-9_-]+",
        "_",
        value,
    ).strip("_")


def get_required_temporal_metadata(object_info):
    """
    Read and validate metadata required to organize
    Persistent Landing.

    Objects with missing or unknown provenance are not
    persisted because that would break the naming convention.
    """

    metadata = object_info.get(
        "Metadata",
        {},
    )

    required_fields = (
        "modality",
        "species_id",
        "source_name",
    )

    validated = {}

    for field in required_fields:
        value = metadata.get(field)

        if (
            not value
            or value.strip().lower() == "unknown"
        ):
            raise ValueError(
                "Missing or invalid Temporal metadata "
                f"'{field}'"
            )

        validated[field] = value

    return validated


# ---------------------------------------------------------
# Persistent Landing key
# ---------------------------------------------------------

def build_persistent_key(
    temporal_key,
    object_info,
):
    """
    Build the Persistent Landing object key.

    Naming convention:

    <source>$<species>$<timestamp>$<hash>.<extension>

    The timestamp corresponds to the ingestion time of the
    object in Temporal Landing and is expressed in UTC with
    second-level precision.
    """

    metadata = get_required_temporal_metadata(
        object_info
    )

    asset_hash, original_filename = (
        parse_temporal_object_key(
            temporal_key
        )
    )

    modality = sanitize_component(
        metadata["modality"]
    )

    species_id = sanitize_component(
        metadata["species_id"]
    )

    source_name = sanitize_component(
        metadata["source_name"]
    )

    extension = Path(
        original_filename
    ).suffix.lower()

    last_modified = object_info[
        "LastModified"
    ]

    ingestion_timestamp = (
        last_modified
        .astimezone(timezone.utc)
        .strftime("%d-%m-%Y_%H-%M-%S")
    )

    persistent_filename = (
        f"{source_name}"
        f"${species_id}"
        f"${ingestion_timestamp}"
        f"${asset_hash}"
        f"{extension}"
    )

    return (
        f"{PERSISTENT_PREFIX}"
        f"{modality}/"
        f"{species_id}/"
        f"{persistent_filename}"
    )


# ---------------------------------------------------------
# Persistent metadata
# ---------------------------------------------------------

def build_persistent_metadata(
    temporal_key,
    object_info,
):
    """
    Build metadata required for provenance and traceability.

    Some fields are URL encoded because S3 metadata is
    transported through HTTP headers and original filenames
    may contain accents or other non-ASCII characters.
    """

    temporal_metadata = (
        get_required_temporal_metadata(
            object_info
        )
    )

    asset_hash, original_filename = (
        parse_temporal_object_key(
            temporal_key
        )
    )

    last_modified = object_info[
        "LastModified"
    ]

    ingestion_timestamp = (
        last_modified
        .astimezone(timezone.utc)
        .isoformat()
    )

    return {
        "modality": temporal_metadata[
            "modality"
        ],
        "species_id": temporal_metadata[
            "species_id"
        ],
        "source_name": temporal_metadata[
            "source_name"
        ],
        "asset_hash": asset_hash,
        "ingestion_timestamp": (
            ingestion_timestamp
        ),
        "original_filename_encoded": quote(
            original_filename,
            safe="",
        ),
        "temporal_object_key_encoded": quote(
            temporal_key,
            safe="",
        ),
    }


# ---------------------------------------------------------
# Incremental processing
# ---------------------------------------------------------

def object_exists(object_key):
    """
    Check whether an object already exists in MinIO.
    """

    try:
        minio_client.head_object(
            Bucket=BUCKET_NAME,
            Key=object_key,
        )

        return True

    except ClientError as error:

        error_code = error.response.get(
            "Error",
            {},
        ).get(
            "Code"
        )

        if error_code in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return False

        raise


# ---------------------------------------------------------
# Landing completion registry
# ---------------------------------------------------------

def build_control_key(temporal_key):
    """
    Build a deterministic control key for one completed
    Landing ingestion.

    The complete Temporal key is hashed so that the registry
    lookup is direct and independent from the organization of
    Persistent Landing.
    """

    control_id = hashlib.sha256(
        temporal_key.encode("utf-8")
    ).hexdigest()

    return (
        f"{CONTROL_COMPLETED_PREFIX}"
        f"{control_id}.json"
    )


def create_completion_marker(
    temporal_key,
    persistent_key,
    object_info,
):
    """
    Record that an asset successfully completed the Landing
    Zone.

    This function must only be called after the Persistent
    object has been verified. The marker is operational state,
    not dataset content and not a Trusted Zone deduplication
    record.
    """

    temporal_metadata = (
        get_required_temporal_metadata(
            object_info
        )
    )

    asset_hash, original_filename = (
        parse_temporal_object_key(
            temporal_key
        )
    )

    control_key = build_control_key(
        temporal_key
    )

    marker = {
        "temporal_key": temporal_key,
        "persistent_key": persistent_key,
        "modality": temporal_metadata["modality"],
        "species_id": temporal_metadata["species_id"],
        "source_name": temporal_metadata["source_name"],
        "asset_hash": asset_hash,
        "original_filename": original_filename,
        "completed_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    body = json.dumps(
        marker,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")

    minio_client.put_object(
        Bucket=BUCKET_NAME,
        Key=control_key,
        Body=body,
        ContentType="application/json",
    )

    if not object_exists(
        control_key
    ):
        raise RuntimeError(
            "Completion marker verification failed: "
            f"{control_key}"
        )

    return control_key


def list_persistent_objects():
    """
    List every data object currently stored in Persistent
    Landing.

    This is used only for one-time control-registry backfill of
    objects created before the registry was introduced.
    """

    paginator = minio_client.get_paginator(
        "list_objects_v2"
    )

    object_keys = []

    for page in paginator.paginate(
        Bucket=BUCKET_NAME,
        Prefix=PERSISTENT_PREFIX,
    ):
        for item in page.get("Contents", []):
            object_keys.append(
                item["Key"]
            )

    return sorted(object_keys)


def backfill_completion_markers():
    """
    Create missing completion markers for Persistent objects
    produced before the control registry existed.

    Persistent metadata already contains the encoded original
    Temporal key, so the same deterministic control identifier
    can be reconstructed without modifying the dataset object.
    """

    persistent_objects = (
        list_persistent_objects()
    )

    created_count = 0
    existing_count = 0
    skipped_count = 0
    error_count = 0

    print(
        "Persistent objects found for backfill: "
        f"{len(persistent_objects)}"
    )
    print()

    for persistent_key in persistent_objects:

        try:
            persistent_info = minio_client.head_object(
                Bucket=BUCKET_NAME,
                Key=persistent_key,
            )

            metadata = persistent_info.get(
                "Metadata",
                {},
            )

            encoded_temporal_key = metadata.get(
                "temporal_object_key_encoded"
            )

            if not encoded_temporal_key:
                print(
                    "SKIP NO TEMPORAL KEY: "
                    f"{persistent_key}"
                )
                skipped_count += 1
                continue

            temporal_key = unquote(
                encoded_temporal_key
            )

            control_key = build_control_key(
                temporal_key
            )

            if object_exists(
                control_key
            ):
                print(
                    "ALREADY MARKED: "
                    f"{persistent_key}"
                )
                existing_count += 1
                continue

            original_filename = unquote(
                metadata.get(
                    "original_filename_encoded",
                    "",
                )
            )

            marker = {
                "temporal_key": temporal_key,
                "persistent_key": persistent_key,
                "modality": metadata.get("modality"),
                "species_id": metadata.get("species_id"),
                "source_name": metadata.get("source_name"),
                "asset_hash": metadata.get("asset_hash"),
                "original_filename": original_filename,
                "completed_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "backfilled": True,
            }

            body = json.dumps(
                marker,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")

            minio_client.put_object(
                Bucket=BUCKET_NAME,
                Key=control_key,
                Body=body,
                ContentType="application/json",
            )

            if not object_exists(
                control_key
            ):
                raise RuntimeError(
                    "Backfill marker verification failed: "
                    f"{control_key}"
                )

            print(
                "CREATED MARKER: "
                f"{persistent_key}"
            )
            created_count += 1

        except Exception as error:
            error_count += 1

            print(
                f"ERROR: {persistent_key}"
            )
            print(
                f"       {error}"
            )

    print()
    print("=" * 70)
    print("Completion registry backfill finished")
    print(f"Created:         {created_count}")
    print(f"Already marked:  {existing_count}")
    print(f"Skipped:         {skipped_count}")
    print(f"Errors:          {error_count}")
    print("=" * 70)


# ---------------------------------------------------------
# Copy Temporal -> Persistent
# ---------------------------------------------------------

def copy_to_persistent(
    temporal_key,
    persistent_key,
    object_info,
):
    """
    Copy one raw object from Temporal Landing to its
    organized location in Persistent Landing.

    File contents are not modified.
    """

    persistent_metadata = (
        build_persistent_metadata(
            temporal_key,
            object_info,
        )
    )

    content_type = object_info.get(
        "ContentType",
        "application/octet-stream",
    )

    minio_client.copy_object(
        Bucket=BUCKET_NAME,
        Key=persistent_key,
        CopySource={
            "Bucket": BUCKET_NAME,
            "Key": temporal_key,
        },
        Metadata=persistent_metadata,
        MetadataDirective="REPLACE",
        ContentType=content_type,
    )


# ---------------------------------------------------------
# Temporal cleanup
# ---------------------------------------------------------

def delete_temporal_object(
    temporal_key,
):
    """
    Delete one object from Temporal Landing after it has
    been successfully persisted.
    """

    minio_client.delete_object(
        Bucket=BUCKET_NAME,
        Key=temporal_key,
    )


# ---------------------------------------------------------
# Persistent processing
# ---------------------------------------------------------

def process_temporal_objects(
    max_items=None,
    dry_run=False,
):
    """
    Process objects from Temporal Landing into Persistent
    Landing.

    Safe processing order:
    1. Read and validate Temporal metadata.
    2. Build the Persistent key and completion-marker key.
    3. If the completion marker already exists, the asset has
       already completed Landing and the Temporal copy can be
       removed.
    4. Otherwise copy to Persistent when needed.
    5. Verify the Persistent object exists.
    6. Create and verify the completion marker.
    7. Delete the Temporal object only after both verifications.

    dry_run=True displays the planned operations without
    modifying MinIO.
    """

    temporal_objects = (
        list_temporal_objects()
    )

    if max_items is not None:
        temporal_objects = (
            temporal_objects[:max_items]
        )

    copied_count = 0
    persistent_existing_count = 0
    already_completed_count = 0
    marker_created_count = 0
    deleted_count = 0
    error_count = 0

    print(
        f"Temporal objects found: "
        f"{len(temporal_objects)}"
    )

    print()

    for temporal_key in temporal_objects:

        try:
            object_info = get_object_info(
                temporal_key
            )

            # Validate provenance before any destructive action.
            get_required_temporal_metadata(
                object_info
            )

            persistent_key = (
                build_persistent_key(
                    temporal_key,
                    object_info,
                )
            )

            control_key = build_control_key(
                temporal_key
            )

            print(
                f"TEMPORAL:   {temporal_key}"
            )

            print(
                f"PERSISTENT: {persistent_key}"
            )

            print(
                f"CONTROL:    {control_key}"
            )

            if dry_run:
                print(
                    "ACTION:     DRY RUN"
                )
                print("-" * 70)
                continue

            if object_exists(
                control_key
            ):
                print(
                    "ACTION:     ALREADY COMPLETED"
                )

                already_completed_count += 1

                delete_temporal_object(
                    temporal_key
                )

                deleted_count += 1

                print(
                    "TEMPORAL:   DELETED"
                )

                print("-" * 70)
                continue

            if object_exists(
                persistent_key
            ):
                print(
                    "ACTION:     PERSISTENT ALREADY EXISTS"
                )

                persistent_existing_count += 1

            else:
                copy_to_persistent(
                    temporal_key,
                    persistent_key,
                    object_info,
                )

                if not object_exists(
                    persistent_key
                ):
                    raise RuntimeError(
                        "Persistent copy verification failed: "
                        f"{persistent_key}"
                    )

                copied_count += 1

                print(
                    "ACTION:     COPIED"
                )

            create_completion_marker(
                temporal_key,
                persistent_key,
                object_info,
            )

            marker_created_count += 1

            print(
                "CONTROL:    CREATED"
            )

            delete_temporal_object(
                temporal_key
            )

            deleted_count += 1

            print(
                "TEMPORAL:   DELETED"
            )

            print("-" * 70)

        except Exception as error:

            error_count += 1

            print(
                f"ERROR: {temporal_key}"
            )

            print(
                f"       {error}"
            )

            print("-" * 70)

    print()
    print("=" * 70)

    print(
        "Persistent Landing processing completed"
    )

    print(
        f"Copied:                     {copied_count}"
    )

    print(
        "Persistent already existed: "
        f"{persistent_existing_count}"
    )

    print(
        "Already completed:          "
        f"{already_completed_count}"
    )

    print(
        "Completion markers created: "
        f"{marker_created_count}"
    )

    print(
        f"Temporal deleted:           {deleted_count}"
    )

    print(
        f"Errors:                     {error_count}"
    )

    print("=" * 70)


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Process EcoSentinel Temporal Landing "
            "objects into Persistent Landing."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show the planned operations without "
            "copying or deleting objects."
        ),
    )

    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help=(
            "Maximum number of Temporal objects "
            "to process."
        ),
    )

    parser.add_argument(
        "--backfill-control",
        action="store_true",
        help=(
            "Create missing completion markers for "
            "Persistent objects created before the "
            "control registry existed."
        ),
    )

    args = parser.parse_args()

    if args.backfill_control:
        backfill_completion_markers()
        return

    process_temporal_objects(
        max_items=args.max_items,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()