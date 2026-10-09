import argparse
import hashlib
import html
import json
import re
import time
from pathlib import Path

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------
# Wikimedia configuration
# ---------------------------------------------------------

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

# Small pause between Wikimedia API requests.
# Retries handle 429 responses if the API asks us to slow down.
REQUEST_DELAY_SECONDS = 0.4


# ---------------------------------------------------------
# Project paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SPECIES_CONFIG = (
    PROJECT_ROOT
    / "config"
    / "species.yaml"
)

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
    """
    Remove basic HTML returned by Wikimedia metadata.
    """

    if not value:
        return None

    value = re.sub(
        r"<[^>]+>",
        "",
        value,
    )

    return html.unescape(value).strip()


def safe_filename(filename, max_length=140):
    """
    Convert a Wikimedia filename into a Windows-safe local
    filename while preserving its file extension.

    Besides replacing invalid Windows characters, long names
    are truncated to avoid path-length errors.
    """

    filename = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        filename,
    )

    # Windows does not allow filenames ending in spaces or dots.
    filename = filename.rstrip(" .")

    path = Path(filename)

    extension = path.suffix
    stem = path.stem

    max_stem_length = (
        max_length
        - len(extension)
    )

    if len(stem) > max_stem_length:
        stem = stem[:max_stem_length]

    return f"{stem}{extension}"


def sha256_file(path):
    """
    Calculate SHA-256 checksum for a local image.
    """

    sha256 = hashlib.sha256()

    with open(path, "rb") as file:
        for chunk in iter(
            lambda: file.read(8192),
            b"",
        ):
            sha256.update(chunk)

    return sha256.hexdigest()


def save_metadata(
    metadata_path,
    downloaded,
):
    """
    Persist acquisition metadata immediately.

    Metadata is saved after every successful asset so that
    other pipeline stages never have to wait for the whole
    species download to finish.
    """

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


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

def load_species():
    """
    Load species configuration from config/species.yaml.
    """

    with open(
        SPECIES_CONFIG,
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    return config["species"]


# ---------------------------------------------------------
# Wikimedia API
# ---------------------------------------------------------

def get_category_members(
    session,
    scientific_name,
):
    """
    Get files directly contained in the Wikimedia Commons
    category corresponding to a scientific species name.
    """

    category = (
        f"Category:{scientific_name}"
    )

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
        for item in data[
            "query"
        ][
            "categorymembers"
        ]
    ]


def get_image_info(
    session,
    title,
):
    """
    Get technical image information and useful provenance
    metadata from Wikimedia Commons in a single API request.

    This avoids making separate requests for technical
    information and licensing metadata.
    """

    params = {
        "action": "query",
        "prop": "imageinfo",
        "titles": title,
        "iiprop": (
            "url|mime|size|extmetadata"
        ),
        "iiextmetadatafilter": (
            "Artist|"
            "LicenseShortName|"
            "LicenseUrl|"
            "Credit"
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

    pages = response.json()[
        "query"
    ][
        "pages"
    ]

    if (
        not pages
        or "imageinfo" not in pages[0]
    ):
        return None

    info = pages[0][
        "imageinfo"
    ][0]

    metadata = info.get(
        "extmetadata",
        {},
    )

    info[
        "clean_metadata"
    ] = {
        key: clean_html(
            value.get("value")
        )
        for key, value
        in metadata.items()
    }

    return info


# ---------------------------------------------------------
# Download
# ---------------------------------------------------------

def download_file(
    session,
    url,
    output_path,
):
    """
    Download one image.
    """

    with session.get(
        url,
        stream=True,
        timeout=60,
    ) as response:

        response.raise_for_status()

        with open(
            output_path,
            "wb",
        ) as file:

            for chunk in response.iter_content(
                chunk_size=8192
            ):
                if chunk:
                    file.write(chunk)


# ---------------------------------------------------------
# Metadata record
# ---------------------------------------------------------

def build_metadata_record(
    species_id,
    scientific_name,
    title,
    info,
    original_name,
    filename,
    output_path,
):
    """
    Build the provenance record associated with one
    downloaded Wikimedia image.
    """

    ext_metadata = info.get(
        "clean_metadata",
        {},
    )

    return {
        "species_id": species_id,
        "scientific_name": scientific_name,
        "source_name": "wikimedia_commons",
        "commons_title": title,
        "source_url": info.get(
            "descriptionurl"
        ),
        "original_filename": original_name,
        "local_filename": filename,
        "mime_type": info.get(
            "mime"
        ),
        "width": info.get(
            "width"
        ),
        "height": info.get(
            "height"
        ),
        "file_size_bytes": info.get(
            "size"
        ),
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


# ---------------------------------------------------------
# Species processing
# ---------------------------------------------------------

def process_species(
    session,
    species,
    limit,
):
    species_id = species["id"]
    scientific_name = (
        species["scientific_name"]
    )

    output_dir = (
        OUTPUT_ROOT
        / species_id
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata_path = (
        output_dir
        / "_metadata.json"
    )

    print()
    print("=" * 60)
    print(
        f"Species: {scientific_name}"
    )
    print(
        f"Target: {limit} images"
    )
    print("=" * 60)

    titles = get_category_members(
        session,
        scientific_name,
    )

    print(
        "Wikimedia candidates found: "
        f"{len(titles)}"
    )

    # -----------------------------------------------------
    # Load previous metadata
    # -----------------------------------------------------

    if metadata_path.exists():

        try:
            with open(
                metadata_path,
                "r",
                encoding="utf-8",
            ) as file:
                downloaded = json.load(
                    file
                )

        except (
            json.JSONDecodeError,
            OSError,
        ):
            print(
                "Warning: existing metadata "
                "could not be read."
            )
            downloaded = []

    else:
        downloaded = []

    # Keep only metadata records whose local asset
    # still exists.
    downloaded = [
        record
        for record in downloaded
        if (
            record.get(
                "local_filename"
            )
            and (
                output_dir
                / record[
                    "local_filename"
                ]
            ).exists()
        )
    ]

    existing_titles = {
        record.get(
            "commons_title"
        )
        for record in downloaded
        if record.get(
            "commons_title"
        )
    }

    existing_filenames = {
        record.get(
            "local_filename"
        )
        for record in downloaded
        if record.get(
            "local_filename"
        )
    }

    print(
        "Images already registered: "
        f"{len(downloaded)}"
    )

    # -----------------------------------------------------
    # Candidate processing
    # -----------------------------------------------------

    for title in titles:

        if len(downloaded) >= limit:
            break

        if title in existing_titles:
            continue

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

        try:
            info = get_image_info(
                session,
                title,
            )

            if not info:
                continue

            mime = info.get(
                "mime"
            )

            if (
                mime
                not in ALLOWED_MIME_TYPES
            ):
                continue

            width = info.get(
                "width",
                0,
            )

            height = info.get(
                "height",
                0,
            )

            if (
                max(
                    width,
                    height,
                )
                < MIN_LONG_SIDE
            ):
                continue

            file_size = info.get(
                "size",
                0,
            )

            max_bytes = (
                MAX_FILE_SIZE_MB
                * 1024
                * 1024
            )

            if file_size > max_bytes:
                continue

            url = info["url"]

            original_name = (
                title.replace(
                    "File:",
                    "",
                    1,
                )
            )

            filename = safe_filename(
                original_name
            )

            output_path = (
                output_dir
                / filename
            )

            # -------------------------------------------------
            # Existing local image without metadata
            # -------------------------------------------------

            if output_path.exists():

                if (
                    filename
                    in existing_filenames
                ):
                    continue

                print(
                    "Recovering metadata for "
                    f"existing file: {filename}"
                )

                record = (
                    build_metadata_record(
                        species_id,
                        scientific_name,
                        title,
                        info,
                        original_name,
                        filename,
                        output_path,
                    )
                )

                downloaded.append(
                    record
                )

                existing_titles.add(
                    title
                )

                existing_filenames.add(
                    filename
                )

                save_metadata(
                    metadata_path,
                    downloaded,
                )

                continue

            # -------------------------------------------------
            # New download
            # -------------------------------------------------

            print(
                f"Downloading "
                f"{len(downloaded) + 1}/"
                f"{limit}: "
                f"{filename}"
            )

            download_file(
                session,
                url,
                output_path,
            )

            record = (
                build_metadata_record(
                    species_id,
                    scientific_name,
                    title,
                    info,
                    original_name,
                    filename,
                    output_path,
                )
            )

            downloaded.append(
                record
            )

            existing_titles.add(
                title
            )

            existing_filenames.add(
                filename
            )

            # Write metadata immediately after each
            # successful asset.
            save_metadata(
                metadata_path,
                downloaded,
            )

        except requests.RequestException as error:

            print(
                f"Error processing "
                f"{title}: {error}"
            )

        except OSError as error:

            print(
                f"Local file error "
                f"for {title}: {error}"
            )

    # Final write as an additional safeguard.
    save_metadata(
        metadata_path,
        downloaded,
    )

    print()
    print(
        "Total available: "
        f"{len(downloaded)} images"
    )

    print(
        f"Metadata: {metadata_path}"
    )


# ---------------------------------------------------------
# HTTP session
# ---------------------------------------------------------

def create_session():
    """
    Create a Wikimedia HTTP session with automatic retries
    for rate limiting and temporary server errors.
    """

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
        allowed_methods=[
            "GET"
        ],
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

    return session


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Download curated wildlife images "
            "from Wikimedia Commons."
        )
    )

    parser.add_argument(
        "--species",
        help=(
            "Species id from "
            "config/species.yaml"
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help=(
            "Number of images "
            "per species"
        ),
    )

    args = parser.parse_args()

    species_list = load_species()

    if args.species:

        species_list = [
            species
            for species
            in species_list
            if (
                species["id"]
                == args.species
            )
        ]

        if not species_list:
            raise ValueError(
                f"Species "
                f"'{args.species}' "
                "not found in "
                "species.yaml"
            )

    session = create_session()

    for species in species_list:
        process_species(
            session,
            species,
            args.limit,
        )


if __name__ == "__main__":
    main()