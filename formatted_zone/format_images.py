"""Convert Persistent Landing images to the canonical JPEG representation.

The Formatted Zone standardizes encoding without resizing, rotating, cropping,
or applying data-quality rules. Original assets remain in Persistent Landing.
"""

import argparse
import logging
import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError


LOGGER = logging.getLogger(__name__)

LANDING_BUCKET = "landing-zone"
FORMATTED_BUCKET = "formatted-zone"
PERSISTENT_PREFIX = "persistent_landing/images/"
FORMATTED_PREFIX = "images/"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
JPEG_QUALITY = 95
FORMAT_VERSION = "1"


def create_s3_client():
    """Create an S3-compatible client using the project's local credentials."""
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    access_key = os.getenv("MINIO_ROOT_USER")
    secret_key = os.getenv("MINIO_ROOT_PASSWORD")
    if not access_key or not secret_key:
        raise RuntimeError("MINIO_ROOT_USER and MINIO_ROOT_PASSWORD are required")

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000"),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def list_persistent_images(client):
    """Yield all objects under the Persistent Landing image prefix."""
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=LANDING_BUCKET, Prefix=PERSISTENT_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith("/"):
                yield key


def build_formatted_key(persistent_key):
    """Mirror the species hierarchy and replace the extension with .jpg."""
    if not persistent_key.startswith(PERSISTENT_PREFIX):
        raise ValueError(f"Unexpected Persistent Landing key: {persistent_key}")

    relative_key = persistent_key[len(PERSISTENT_PREFIX):]
    path = PurePosixPath(relative_key)
    if len(path.parts) != 2 or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported image path or extension: {persistent_key}")

    return f"{FORMATTED_PREFIX}{path.with_suffix('.jpg')}"


def validate_persistent_metadata(persistent_key, metadata):
    """Require the provenance fields needed by the Formatted Zone."""
    species_id = PurePosixPath(persistent_key).parent.name
    required_fields = ("modality", "species_id", "source_name", "asset_hash")

    for field in required_fields:
        value = metadata.get(field)
        if not value or value.strip().lower() == "unknown":
            raise ValueError(f"Missing or invalid metadata '{field}': {persistent_key}")

    if metadata["modality"] != "images" or metadata["species_id"] != species_id:
        raise ValueError(f"Inconsistent species/modality metadata: {persistent_key}")


def get_existing_formatted(client, key):
    """Return the destination object's headers, or None when it is absent."""
    try:
        return client.head_object(Bucket=FORMATTED_BUCKET, Key=key)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code in {"404", "NotFound", "NoSuchKey"}:
            return None
        raise


def verify_existing_formatted(persistent_key, formatted_key, object_info):
    """Ensure an existing destination belongs to the same source and format policy."""
    metadata = object_info.get("Metadata", {})
    encoded_source = metadata.get("source_persistent_key_encoded", "")

    if (
        unquote(encoded_source) != persistent_key
        or metadata.get("format_version") != FORMAT_VERSION
        or metadata.get("formatted_format") != "jpeg"
        or metadata.get("color_mode") != "rgb"
        or metadata.get("jpeg_quality") != str(JPEG_QUALITY)
        or object_info.get("ContentType") != "image/jpeg"
        or object_info.get("ContentLength", 0) == 0
    ):
        raise ValueError(
            f"Existing output conflicts with the current format contract: {formatted_key}"
        )


def read_raw_image(client, persistent_key):
    """Download the raw bytes of one Persistent Landing image."""
    response = client.get_object(Bucket=LANDING_BUCKET, Key=persistent_key)
    body = response["Body"]
    try:
        return body.read()
    finally:
        body.close()


def to_rgb(image):
    """Produce an RGB image, using white beneath any transparent pixels."""
    has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
    if has_alpha:
        overlay = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        background.alpha_composite(overlay)
        return background.convert("RGB")

    return image.convert("RGB")


def convert_to_jpeg(raw_bytes):
    """
    Convert an image to the canonical JPEG format.

    Preserves the original dimensions and EXIF orientation.
    For MPO files, only the primary frame is converted.
    """
    with Image.open(BytesIO(raw_bytes)) as source:
        source_format = source.format

        if source_format not in SUPPORTED_IMAGE_FORMATS:
            raise ValueError(
                f"Unsupported image encoding: {source_format}"
            )

        # MPO files may contain multiple images.
        # Only the primary frame is used for the canonical JPEG.
        if source_format == "MPO":
            source.seek(0)

        save_options = {
            "format": "JPEG",
            "quality": JPEG_QUALITY,
        }

        # Preserve EXIF orientation without rotating the image.
        exif = source.getexif()
        if exif:
            save_options["exif"] = exif.tobytes()

        # Preserve compatible color profiles.
        icc_profile = source.info.get("icc_profile")
        if icc_profile and source.mode in {"RGB", "RGBA"}:
            save_options["icc_profile"] = icc_profile

        rgb = to_rgb(source)

        with BytesIO() as output:
            rgb.save(output, **save_options)

            return (
                output.getvalue(),
                source_format.lower(),
            )


def build_formatted_metadata(persistent_key, original_metadata, source_format):
    """Copy source lineage and describe the canonical representation."""
    metadata = dict(original_metadata)
    metadata.update({
        "source_persistent_key_encoded": quote(persistent_key, safe=""),
        "original_format": source_format,
        "formatted_format": "jpeg",
        "color_mode": "rgb",
        "jpeg_quality": str(JPEG_QUALITY),
        "format_version": FORMAT_VERSION,
        "formatted_at": datetime.now(timezone.utc).isoformat(),
    })
    return metadata


def upload_formatted_image(client, key, image_bytes, metadata):
    """Store one canonical image and verify its persisted byte length."""
    client.put_object(
        Bucket=FORMATTED_BUCKET,
        Key=key,
        Body=image_bytes,
        ContentLength=len(image_bytes),
        ContentType="image/jpeg",
        Metadata=metadata,
    )

    stored = client.head_object(Bucket=FORMATTED_BUCKET, Key=key)
    if stored.get("ContentLength") != len(image_bytes):
        raise RuntimeError(f"Formatted upload could not be verified: {key}")


def format_images(client, max_items=None, dry_run=False):
    """Process images incrementally and report converted, skipped and failed assets.

    max_items limits newly converted images (or planned conversions in dry-run).
    Previously formatted images do not count towards this limit.
    """
    stats = {"discovered": 0, "converted": 0, "skipped": 0, "planned": 0, "errors": 0}

    for persistent_key in list_persistent_images(client):
        stats["discovered"] += 1
        try:
            formatted_key = build_formatted_key(persistent_key)
            persistent_info = client.head_object(Bucket=LANDING_BUCKET, Key=persistent_key)
            persistent_metadata = persistent_info.get("Metadata", {})
            validate_persistent_metadata(persistent_key, persistent_metadata)

            existing = get_existing_formatted(client, formatted_key)
            if existing is not None:
                verify_existing_formatted(persistent_key, formatted_key, existing)
                stats["skipped"] += 1
                LOGGER.info("SKIP  %s", formatted_key)
                continue

            if dry_run:
                stats["planned"] += 1
                LOGGER.info("PLAN  %s -> %s", persistent_key, formatted_key)
            else:
                raw_bytes = read_raw_image(client, persistent_key)
                image_bytes, source_format = convert_to_jpeg(raw_bytes)
                metadata = build_formatted_metadata(
                    persistent_key, persistent_metadata, source_format
                )
                upload_formatted_image(client, formatted_key, image_bytes, metadata)
                stats["converted"] += 1
                LOGGER.info("DONE  %s -> %s", persistent_key, formatted_key)

            if max_items is not None and stats["converted"] + stats["planned"] >= max_items:
                break

        except (ClientError, OSError, ValueError, UnidentifiedImageError, RuntimeError) as error:
            stats["errors"] += 1
            LOGGER.error("ERROR %s: %s", persistent_key, error)

    return stats


def parse_args():
    """Parse options for controlled runs and non-destructive previews."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-items", type=int, metavar="N", help="Maximum new images")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    args = parser.parse_args()
    if args.max_items is not None and args.max_items < 1:
        parser.error("--max-items must be greater than zero")
    return args


def main():
    """Connect to storage, run image formatting and print a compact summary."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    client = create_s3_client()
    stats = format_images(client, max_items=args.max_items, dry_run=args.dry_run)

    print("\nFormatted image processing summary")
    for name, count in stats.items():
        print(f"{name.capitalize():<12}: {count}")

    if stats["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
