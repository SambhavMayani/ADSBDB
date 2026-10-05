import os
from pathlib import Path
import hashlib
import boto3
from dotenv import load_dotenv
from botocore.exceptions import ClientError
import mimetypes
# ---------------------------------------------------------
# Project paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DATASET_ROOT = (
    PROJECT_ROOT
    / "data"
    / "raw_dataset"
)


# ---------------------------------------------------------
# MinIO configuration
# ---------------------------------------------------------

BUCKET_NAME = "landing-zone"

TEMPORAL_PREFIX = "temporal_landing"


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
# Local dataset discovery
# ---------------------------------------------------------

SUPPORTED_MODALITIES = {
    "images",
    "audio",
    "text",
}


def discover_local_files():
    """
    Discover all multimodal data files stored under
    data/raw_dataset/ without hardcoding species
    or filenames.

    Auxiliary acquisition metadata files are ignored.
    """

    discovered_files = []

    for modality_dir in RAW_DATASET_ROOT.iterdir():

        if not modality_dir.is_dir():
            continue

        modality = modality_dir.name

        if modality not in SUPPORTED_MODALITIES:
            continue

        for file_path in modality_dir.rglob("*"):

            if not file_path.is_file():
                continue

            # Acquisition metadata is auxiliary information,
            # not a multimodal data asset.
            if file_path.name == "_metadata.json":
                continue

            discovered_files.append(
                {
                    "path": file_path,
                    "modality": modality,
                    "relative_path": file_path.relative_to(
                        RAW_DATASET_ROOT
                    ),
                }
            )

    return discovered_files

def get_source_name(file_info):
    """
    Get the original data source for an asset from the
    acquisition metadata stored next to the raw files.

    Example:
    data/raw_dataset/images/lynx_pardinus/_metadata.json
    """

    local_path = file_info["path"]
    metadata_path = local_path.parent / "_metadata.json"

    if not metadata_path.exists():
        return "unknown"

    import json

    with open(
        metadata_path,
        "r",
        encoding="utf-8",
    ) as file:
        metadata_records = json.load(file)

    for record in metadata_records:
        if record.get("local_filename") == local_path.name:
            return record.get(
                "source_name",
                "unknown",
            )

    return "unknown"

# ---------------------------------------------------------
# MinIO object key
# ---------------------------------------------------------

def build_object_key(file_info):
    """
    Build a stable raw object key for Temporal Landing.

    Temporal Landing does not apply the final organization
    by modality/species. That organization will be applied
    when moving data to Persistent Landing.

    The SHA-256 hash makes the key deterministic and allows
    incremental ingestion without changing the raw file.
    """

    local_path = file_info["path"]

    sha256 = hashlib.sha256()

    with open(local_path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)

    file_hash = sha256.hexdigest()[:16]

    return (
        f"{TEMPORAL_PREFIX}/"
        f"{file_hash}__{local_path.name}"
    )


def build_object_metadata(file_info):
    """
    Build the minimal metadata required to later organize
    raw Temporal Landing objects into Persistent Landing.
    """

    relative_path = file_info["relative_path"]

    # Expected structure:
    # modality/species_id/filename
    path_parts = relative_path.parts

    if len(path_parts) < 3:
        raise ValueError(
            f"Unexpected dataset structure: {relative_path}"
        )

    modality = path_parts[0]
    species_id = path_parts[1]

    source_name = get_source_name(
        file_info
    )

    return {
        "modality": modality,
        "species_id": species_id,
        "source_name": source_name,
    }

# ---------------------------------------------------------
# Incremental ingestion
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
            {}
        ).get("Code")

        if error_code in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return False

        raise


# ---------------------------------------------------------
# File upload
# ---------------------------------------------------------

def upload_file(file_info, object_key):
    """
    Upload one local raw file to the Temporal Landing area
    and attach the minimal metadata required for later
    Persistent Landing organization.
    """

    local_path = file_info["path"]

    object_metadata = build_object_metadata(
        file_info
    )

    content_type, _ = mimetypes.guess_type(
        local_path.name
    )

    if content_type is None:
        content_type = "application/octet-stream"

    minio_client.upload_file(
        Filename=str(local_path),
        Bucket=BUCKET_NAME,
        Key=object_key,
        ExtraArgs={
            "Metadata": object_metadata,
            "ContentType": content_type,
        },
    )

    print(
        f"Uploaded: {local_path.name} "
        f"-> {BUCKET_NAME}/{object_key} "
        f"[{content_type}]"
    )
# ---------------------------------------------------------
# Preview
# ---------------------------------------------------------

def preview_ingestion():
    """
    Show which local files would be ingested into
    Temporal Landing without uploading anything.
    """

    files = discover_local_files()

    print(f"Discovered files: {len(files)}")
    print()

    for file_info in files:
        object_key = build_object_key(file_info)

        print(
            f"{file_info['relative_path']} "
            f"-> {BUCKET_NAME}/{object_key}"
        )

# ---------------------------------------------------------
# Incremental ingestion
# ---------------------------------------------------------

def ingest_dataset(max_uploads=None):
    """
    Ingest discovered raw assets into Temporal Landing.

    Files already present in MinIO are skipped so that
    repeated executions do not re-ingest the same object.

    max_uploads can be used for controlled test executions.
    """

    files = discover_local_files()

    uploaded_count = 0
    skipped_count = 0

    print(f"Discovered assets: {len(files)}")
    print()

    for file_info in files:

        if (
            max_uploads is not None
            and uploaded_count >= max_uploads
        ):
            break

        object_key = build_object_key(file_info)

        if object_exists(object_key):
            print(
                f"SKIP: {file_info['relative_path']}"
            )
            skipped_count += 1
            continue

        upload_file(
            file_info,
            object_key,
        )

        uploaded_count += 1

    print()
    print("=" * 60)
    print("Temporal Landing ingestion completed")
    print(f"Uploaded: {uploaded_count}")
    print(f"Skipped:  {skipped_count}")
    print("=" * 60)


if __name__ == "__main__":
    ingest_dataset()