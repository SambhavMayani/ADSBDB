import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import requests
import yaml


API_URL = "https://commons.wikimedia.org/w/api.php"

USER_AGENT = (
    "EcoSentinel-ADSDB/1.0 "
    "(academic multimodal data management project)"
)

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

MIN_LONG_SIDE = 1200
MAX_FILE_SIZE_MB = 15


# ---------------------------------------------------------
# Project paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SPECIES_CONFIG = PROJECT_ROOT / "config" / "species.yaml"

OUTPUT_ROOT = (
    PROJECT_ROOT
    / "data"
    / "raw_dataset"
    / "images"
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clean_html(value):
    """Remove basic HTML returned by Wikimedia metadata."""
    if not value:
        return None

    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def safe_filename(filename):
    """
    Remove characters that cannot be used safely in Windows filenames.
    """
    return re.sub(r'[<>:"/\\|?*]', "_", filename)


def sha256_file(path):
    """Calculate SHA-256 checksum for an image."""
    sha256 = hashlib.sha256()

    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

def load_species():
    """Load species configuration from config/species.yaml."""
    with open(SPECIES_CONFIG, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    return config["species"]


# ---------------------------------------------------------
# Wikimedia API
# ---------------------------------------------------------

def get_category_members(session, scientific_name):
    """
    Get files directly contained in the Wikimedia Commons
    category corresponding to a scientific species name.
    """

    category = f"Category:{scientific_name}"

    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "file",
        "cmlimit": "100",
        "format": "json",
        "formatversion": "2",
    }

    response = session.get(
        API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    return [
        item["title"]
        for item in data["query"]["categorymembers"]
    ]


def get_basic_image_info(session, title):
    """
    Get URL, MIME type, file size and dimensions.
    """

    params = {
        "action": "query",
        "prop": "imageinfo",
        "titles": title,
        "iiprop": "url|mime|size",
        "format": "json",
        "formatversion": "2",
    }

    response = session.get(
        API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    pages = response.json()["query"]["pages"]

    if not pages or "imageinfo" not in pages[0]:
        return None

    return pages[0]["imageinfo"][0]


def get_extended_metadata(session, title):
    """
    Get only metadata useful for provenance and licensing.
    """

    params = {
        "action": "query",
        "prop": "imageinfo",
        "titles": title,
        "iiprop": "extmetadata",
        "iiextmetadatafilter": (
            "Artist|LicenseShortName|LicenseUrl|Credit"
        ),
        "format": "json",
        "formatversion": "2",
    }

    response = session.get(
        API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    pages = response.json()["query"]["pages"]

    if not pages or "imageinfo" not in pages[0]:
        return {}

    metadata = pages[0]["imageinfo"][0].get(
        "extmetadata",
        {},
    )

    result = {}

    for key, value in metadata.items():
        result[key] = clean_html(value.get("value"))

    return result


# ---------------------------------------------------------
# Download
# ---------------------------------------------------------

def download_file(session, url, output_path):
    """Download one image."""

    with session.get(
        url,
        stream=True,
        timeout=60,
    ) as response:

        response.raise_for_status()

        with open(output_path, "wb") as file:
            for chunk in response.iter_content(
                chunk_size=8192
            ):
                if chunk:
                    file.write(chunk)


# ---------------------------------------------------------
# Species processing
# ---------------------------------------------------------

def process_species(session, species, limit):
    species_id = species["id"]
    scientific_name = species["scientific_name"]

    output_dir = OUTPUT_ROOT / species_id
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = output_dir / "_metadata.json"

    print()
    print("=" * 60)
    print(f"Species: {scientific_name}")
    print(f"Target: {limit} images")
    print("=" * 60)

    titles = get_category_members(
        session,
        scientific_name,
    )

    print(
        f"Wikimedia candidates found: {len(titles)}"
    )

    # Load metadata from previous executions so that
    # existing images count towards the requested limit.
    if metadata_path.exists():
        with open(
            metadata_path,
            "r",
            encoding="utf-8",
        ) as file:
            downloaded = json.load(file)

        # Keep only metadata records whose local file
        # still exists on disk.
        downloaded = [
            record
            for record in downloaded
            if (
                record.get("local_filename")
                and (
                    output_dir
                    / record["local_filename"]
                ).exists()
            )
        ]
    else:
        downloaded = []

    existing_titles = {
        record.get("commons_title")
        for record in downloaded
    }

    print(
        f"Images already available: {len(downloaded)}"
    )

    for title in titles:

        if len(downloaded) >= limit:
            break

        # Skip Wikimedia files already downloaded
        # in a previous execution.
        if title in existing_titles:
            continue
        # Avoid hitting Wikimedia Commons API rate limits.
        time.sleep(1)

        try:
            info = get_basic_image_info(
                session,
                title,
            )

            if not info:
                continue

            mime = info.get("mime")

            if mime not in ALLOWED_MIME_TYPES:
                continue

            width = info.get("width", 0)
            height = info.get("height", 0)

            if max(width, height) < MIN_LONG_SIDE:
                continue

            file_size = info.get("size", 0)

            max_bytes = (
                MAX_FILE_SIZE_MB
                * 1024
                * 1024
            )

            if file_size > max_bytes:
                continue

            url = info["url"]

            original_name = title.replace(
                "File:",
                "",
                1,
            )

            filename = safe_filename(
                original_name
            )

            output_path = (
                output_dir / filename
            )

            # Extra safeguard in case a file exists
            # locally but is missing from metadata.
            if output_path.exists():
                print(
                    f"Already exists locally: {filename}"
                )
                continue

            print(
                f"Downloading "
                f"{len(downloaded) + 1}/{limit}: "
                f"{filename}"
            )

            download_file(
                session,
                url,
                output_path,
            )

            ext_metadata = get_extended_metadata(
                session,
                title,
            )

            record = {
                "species_id": species_id,
                "scientific_name": scientific_name,
                "source_name": "wikimedia_commons",
                "commons_title": title,
                "source_url": info.get(
                    "descriptionurl"
                ),
                "original_filename": original_name,
                "local_filename": filename,
                "mime_type": mime,
                "width": width,
                "height": height,
                "file_size_bytes": file_size,
                "license": ext_metadata.get(
                    "LicenseShortName"
                ),
                "license_url": ext_metadata.get(
                    "LicenseUrl"
                ),
                "creator": ext_metadata.get(
                    "Artist"
                ),
                "credit": ext_metadata.get(
                    "Credit"
                ),
                "sha256": sha256_file(
                    output_path
                ),
            }

            downloaded.append(record)
            existing_titles.add(title)

        except requests.RequestException as error:
            print(
                f"Error processing {title}: {error}"
            )

    with open(
        metadata_path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            downloaded,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print(
        f"Total available: {len(downloaded)} images"
    )

    print(
        f"Metadata: {metadata_path}"
    )


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--species",
        help="Species id from species.yaml",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of images per species",
    )

    args = parser.parse_args()

    species_list = load_species()

    if args.species:

        species_list = [
            species
            for species in species_list
            if species["id"] == args.species
        ]

        if not species_list:
            raise ValueError(
                f"Species '{args.species}' "
                "not found in species.yaml"
            )

    session = requests.Session()

    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy
    )

    session.mount(
        "https://",
        adapter,
    )

    session.headers.update(
        {
            "User-Agent": USER_AGENT
        }
    )

    for species in species_list:
        process_species(
            session,
            species,
            args.limit,
        )


if __name__ == "__main__":
    main()