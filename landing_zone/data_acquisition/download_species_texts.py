import argparse
import hashlib
import json
import re
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from orchestration.files import atomic_json_write

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------
# Source configuration
# ---------------------------------------------------------

WIKIPEDIA_API_URL = "https://{language}.wikipedia.org/w/api.php"

WIKIPEDIA_LICENSE = "CC BY-SA 4.0"
WIKIPEDIA_LICENSE_URL = (
    "https://creativecommons.org/licenses/by-sa/4.0/"
)

GBIF_API_URL = "https://api.gbif.org/v1"

GBIF_PAGE_SIZE = 100
GBIF_MAX_PAGES = 10

USER_AGENT = (
    "EcoSentinel-ADSDB/1.0 "
    "(academic multimodal data management project)"
)

SUPPORTED_SOURCES = (
    "wikipedia",
    "gbif",
)

DEFAULT_LANGUAGES = (
    "es",
    "en",
)

# GBIF aggregates descriptions from many checklists. Very short
# records are usually vernacular names or placeholder values
# rather than descriptive text.
DEFAULT_GBIF_MIN_CHARS = 200

# Description types that are taxonomic lists rather than prose.
EXCLUDED_GBIF_TYPES = {
    "child_taxa",
    "vernacular_names",
    "synonyms",
}

# GBIF uses ISO 639-2 codes while Wikipedia uses ISO 639-1.
LANGUAGE_CODES = {
    "eng": "en",
    "spa": "es",
    "por": "pt",
    "cat": "ca",
    "fra": "fr",
    "fre": "fr",
    "deu": "de",
    "ger": "de",
}

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
    / "text"
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def sanitize_component(value):
    """
    Convert an identifier into a safe filename component.
    """

    value = str(value).strip().lower()

    return re.sub(
        r"[^a-z0-9_-]+",
        "_",
        value,
    ).strip("_")


def normalize_language(code):
    """
    Map source language codes to ISO 639-1 when known.
    """

    if not code:
        return None

    code = code.strip().lower()

    return LANGUAGE_CODES.get(
        code,
        code,
    )


def contains_html(text):
    return bool(
        re.search(
            r"<[a-zA-Z/][^>]*>",
            text,
        )
    )


def sha256_file(path):
    """
    Calculate SHA-256 checksum for a local text asset.
    """

    sha256 = hashlib.sha256()

    with open(path, "rb") as file:
        for chunk in iter(
            lambda: file.read(8192),
            b"",
        ):
            sha256.update(chunk)

    return sha256.hexdigest()


def write_text_file(
    output_path,
    text,
):
    """
    Write the text exactly as returned by the source.

    The newline mode is fixed so that the same content always
    produces the same bytes (and SHA-256) on every OS.
    """

    with open(
        output_path,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        file.write(text)


def load_metadata(
    metadata_path,
    output_dir,
):
    """
    Load previous acquisition metadata, keeping only records
    whose local asset still exists.
    """

    if not metadata_path.exists():
        return []

    try:
        with open(
            metadata_path,
            "r",
            encoding="utf-8",
        ) as file:
            records = json.load(file)

    except (
        json.JSONDecodeError,
        OSError,
    ):
        raise ValueError("Existing acquisition metadata is unreadable; preserving it")

    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError("Acquisition metadata must be an array of records")
    return [
        record
        for record in records
        if (
            record.get("local_filename")
            and (
                output_dir
                / record["local_filename"]
            ).exists()
        )
    ]


def save_metadata(metadata_path, records):
    """Publish a complete registry atomically; preserve the previous one on failure."""
    atomic_json_write(metadata_path, records)


def record_identity(record):
    return (
        record.get("source_name"),
        record.get("source_record_id"),
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
# Wikipedia API
# ---------------------------------------------------------

def get_wikipedia_article(
    session,
    language,
    title,
):
    """
    Get the plain-text extract of one Wikipedia article.

    Scientific names usually redirect to the main species
    article (for example "Lynx pardinus" -> "Iberian lynx"),
    so redirects are followed.
    """

    params = {
        "action": "query",
        "prop": "extracts|info|revisions|pageprops",
        "explaintext": "1",
        "exsectionformat": "wiki",
        "inprop": "url",
        "rvprop": "ids|timestamp",
        "ppprop": "disambiguation",
        "redirects": "1",
        "titles": title,
        "format": "json",
        "formatversion": "2",
    }

    response = session.get(
        WIKIPEDIA_API_URL.format(
            language=language
        ),
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    pages = response.json().get(
        "query",
        {},
    ).get(
        "pages",
        [],
    )

    if not pages:
        return None

    page = pages[0]

    if (
        page.get("missing")
        or page.get("invalid")
        or "disambiguation" in page.get(
            "pageprops",
            {},
        )
        or not page.get("extract", "").strip()
    ):
        return None

    return page


def candidate_wikipedia_titles(
    species,
    language,
):
    """
    Titles tried in order. The scientific name is the most
    reliable lookup; the common name is a fallback.
    """

    titles = [
        species["scientific_name"]
    ]

    common_name = species.get(
        f"common_name_{language}"
    )

    if common_name:
        titles.append(common_name)

    return titles


def acquire_wikipedia(
    session,
    species,
    languages,
    output_dir,
    records,
    metadata_path,
):
    species_id = species["id"]
    scientific_name = species["scientific_name"]

    existing_ids = {
        record_identity(record)
        for record in records
    }

    for language in languages:

        page = None

        for title in candidate_wikipedia_titles(
            species,
            language,
        ):
            time.sleep(
                REQUEST_DELAY_SECONDS
            )

            page = get_wikipedia_article(
                session,
                language,
                title,
            )

            if page:
                break

        if not page:
            print(
                f"Wikipedia ({language}): "
                "no article found"
            )
            continue

        source_record_id = (
            f"{language}:{page['pageid']}"
        )

        if (
            "wikipedia",
            source_record_id,
        ) in existing_ids:
            print(
                f"Wikipedia ({language}): "
                "already registered"
            )
            continue

        revision = (
            page.get("revisions")
            or [{}]
        )[0]

        filename = (
            f"wikipedia_{language}_"
            f"{species_id}.txt"
        )

        output_path = output_dir / filename

        print(
            f"Wikipedia ({language}): "
            f"{page['title']} -> {filename}"
        )

        write_text_file(
            output_path,
            page["extract"],
        )

        record = {
            "species_id": species_id,
            "scientific_name": scientific_name,
            "source_name": "wikipedia",
            "source_record_id": source_record_id,
            "title": page["title"],
            "language": language,
            "source_url": page.get("fullurl"),
            "revision_id": revision.get("revid"),
            "revision_timestamp": revision.get(
                "timestamp"
            ),
            "local_filename": filename,
            "mime_type": "text/plain",
            "char_count": len(page["extract"]),
            "file_size_bytes": output_path.stat().st_size,
            "license": WIKIPEDIA_LICENSE,
            "license_url": WIKIPEDIA_LICENSE_URL,
            "creator": "Wikipedia contributors",
            "sha256": sha256_file(output_path),
        }

        records.append(record)
        existing_ids.add(
            record_identity(record)
        )

        save_metadata(
            metadata_path,
            records,
        )


# ---------------------------------------------------------
# GBIF API
# ---------------------------------------------------------

def get_gbif_taxon_key(
    session,
    scientific_name,
):
    """
    Resolve a scientific name to its GBIF Backbone taxon key.
    """

    response = session.get(
        f"{GBIF_API_URL}/species/match",
        params={
            "name": scientific_name,
            "strict": "true",
        },
        timeout=30,
    )

    response.raise_for_status()

    match = response.json()

    if match.get("matchType") not in {
        "EXACT",
        "FUZZY",
    }:
        return None

    return match.get("usageKey")


def get_gbif_descriptions(
    session,
    taxon_key,
):
    """
    Get every description attached to a GBIF taxon, following
    pagination up to GBIF_MAX_PAGES.
    """

    descriptions = []

    for page in range(GBIF_MAX_PAGES):

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

        response = session.get(
            f"{GBIF_API_URL}/species/"
            f"{taxon_key}/descriptions",
            params={
                "limit": GBIF_PAGE_SIZE,
                "offset": page * GBIF_PAGE_SIZE,
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        descriptions.extend(
            data.get("results", [])
        )

        if data.get(
            "endOfRecords",
            True,
        ):
            break

    return descriptions


def get_gbif_dataset(
    session,
    source_taxon_key,
    cache,
):
    """
    Get the dataset (title, license) that contributed a
    description. Licenses are defined per dataset in GBIF.
    """

    if source_taxon_key in cache:
        return cache[source_taxon_key]

    dataset = {}

    try:
        time.sleep(
            REQUEST_DELAY_SECONDS
        )

        taxon = session.get(
            f"{GBIF_API_URL}/species/"
            f"{source_taxon_key}",
            timeout=30,
        )

        taxon.raise_for_status()

        dataset_key = taxon.json().get(
            "datasetKey"
        )

        if dataset_key:
            time.sleep(
                REQUEST_DELAY_SECONDS
            )

            response = session.get(
                f"{GBIF_API_URL}/dataset/"
                f"{dataset_key}",
                timeout=30,
            )

            response.raise_for_status()

            data = response.json()

            dataset = {
                "dataset_key": dataset_key,
                "dataset_title": data.get("title"),
                "license_url": data.get("license"),
            }

    except requests.RequestException as error:
        print(
            "Warning: GBIF dataset lookup failed "
            f"for taxon {source_taxon_key}: {error}"
        )

    cache[source_taxon_key] = dataset

    return dataset


def license_name_from_url(url):
    """
    Derive a short license name from a Creative Commons URL.
    """

    if not url:
        return None

    url = url.lower()

    if "publicdomain/zero" in url:
        return "CC0 1.0"

    match = re.search(
        r"licenses/([a-z-]+)/([0-9.]+)",
        url,
    )

    if match:
        return (
            f"CC {match.group(1).upper()} "
            f"{match.group(2)}"
        )

    return None


def acquire_gbif(
    session,
    species,
    output_dir,
    records,
    metadata_path,
    limit,
    min_chars,
    dataset_cache,
):
    species_id = species["id"]
    scientific_name = species["scientific_name"]

    registered = [
        record
        for record in records
        if record.get("source_name") == "gbif"
    ]

    existing_ids = {
        record_identity(record)
        for record in records
    }

    if len(registered) >= limit:
        print(
            "GBIF: target already reached "
            f"({len(registered)}/{limit})"
        )
        return

    taxon_key = get_gbif_taxon_key(
        session,
        scientific_name,
    )

    if not taxon_key:
        print("GBIF: taxon not found")
        return

    descriptions = get_gbif_descriptions(
        session,
        taxon_key,
    )

    candidates = [
        description
        for description in descriptions
        if (
            len(
                (
                    description.get("description")
                    or ""
                ).strip()
            ) >= min_chars
            and sanitize_component(
                description.get("type") or ""
            ) not in EXCLUDED_GBIF_TYPES
        )
    ]

    print(
        "GBIF descriptions found: "
        f"{len(descriptions)} "
        f"({len(candidates)} usable, >= "
        f"{min_chars} chars)"
    )

    for description in candidates:

        if len(registered) >= limit:
            break

        source_record_id = str(
            description["key"]
        )

        if (
            "gbif",
            source_record_id,
        ) in existing_ids:
            continue

        text = description["description"]

        description_type = sanitize_component(
            description.get("type")
            or "description"
        )

        # Raw content is preserved. Some checklists publish
        # HTML, which is kept as .html for the Formatted Zone.
        extension = (
            ".html"
            if contains_html(text)
            else ".txt"
        )

        filename = (
            f"gbif_{source_record_id}_"
            f"{description_type}{extension}"
        )

        output_path = output_dir / filename

        dataset = get_gbif_dataset(
            session,
            description.get("sourceTaxonKey"),
            dataset_cache,
        )

        print(
            "Downloading GBIF "
            f"{len(registered) + 1}/{limit}: "
            f"{filename}"
        )

        try:
            write_text_file(
                output_path,
                text,
            )

        except OSError as error:
            print(
                "Local file error for "
                f"{filename}: {error}"
            )
            continue

        license_url = dataset.get(
            "license_url"
        )

        record = {
            "species_id": species_id,
            "scientific_name": scientific_name,
            "source_name": "gbif",
            "source_record_id": source_record_id,
            "title": (
                f"{scientific_name} - "
                f"{description.get('type') or 'description'}"
            ),
            "description_type": description.get(
                "type"
            ),
            "language": normalize_language(
                description.get("language")
            ),
            "source_url": (
                "https://www.gbif.org/species/"
                f"{taxon_key}"
            ),
            "gbif_taxon_key": taxon_key,
            "gbif_source_taxon_key": description.get(
                "sourceTaxonKey"
            ),
            "dataset_key": dataset.get(
                "dataset_key"
            ),
            "dataset_title": (
                dataset.get("dataset_title")
                or description.get("source")
            ),
            "local_filename": filename,
            "mime_type": (
                "text/html"
                if extension == ".html"
                else "text/plain"
            ),
            "char_count": len(text),
            "file_size_bytes": output_path.stat().st_size,
            "license": license_name_from_url(
                license_url
            ),
            "license_url": license_url,
            "creator": description.get("creator"),
            "sha256": sha256_file(output_path),
        }

        records.append(record)
        registered.append(record)
        existing_ids.add(
            record_identity(record)
        )

        save_metadata(
            metadata_path,
            records,
        )


# ---------------------------------------------------------
# Species processing
# ---------------------------------------------------------

def process_species(
    session,
    species,
    sources,
    languages,
    gbif_limit,
    gbif_min_chars,
    dataset_cache,
):
    species_id = species["id"]
    scientific_name = species["scientific_name"]

    output_dir = OUTPUT_ROOT / species_id

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
    print(f"Species: {scientific_name}")
    print(f"Sources: {', '.join(sources)}")
    print("=" * 60)

    records = load_metadata(
        metadata_path,
        output_dir,
    )

    print(
        "Texts already registered: "
        f"{len(records)}"
    )

    errors = 0
    if "wikipedia" in sources:
        try:
            acquire_wikipedia(
                session,
                species,
                languages,
                output_dir,
                records,
                metadata_path,
            )

        except requests.RequestException as error:
            errors += 1
            print(f"Wikipedia error: {error}")

        except OSError as error:
            errors += 1
            print(f"Local file error: {error}")

    if "gbif" in sources:
        try:
            acquire_gbif(
                session,
                species,
                output_dir,
                records,
                metadata_path,
                gbif_limit,
                gbif_min_chars,
                dataset_cache,
            )

        except requests.RequestException as error:
            errors += 1
            print(f"GBIF error: {error}")

    # Final write as an additional safeguard.
    save_metadata(
        metadata_path,
        records,
    )

    print()
    print(
        "Total available: "
        f"{len(records)} texts"
    )
    print(f"Metadata: {metadata_path}")

    return errors


# ---------------------------------------------------------
# HTTP session
# ---------------------------------------------------------

def create_session():
    """
    Create an HTTP session with automatic retries for rate
    limiting and temporary server errors.
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
            "Download descriptive species texts "
            "from Wikipedia and GBIF."
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
        "--sources",
        nargs="+",
        choices=SUPPORTED_SOURCES,
        default=list(SUPPORTED_SOURCES),
        help="Text sources to query",
    )

    parser.add_argument(
        "--languages",
        nargs="+",
        default=list(DEFAULT_LANGUAGES),
        help=(
            "Wikipedia language editions "
            "(e.g. es en)"
        ),
    )

    parser.add_argument(
        "--gbif-limit",
        type=int,
        default=10,
        help=(
            "Maximum number of GBIF descriptions "
            "per species"
        ),
    )

    parser.add_argument(
        "--gbif-min-chars",
        type=int,
        default=DEFAULT_GBIF_MIN_CHARS,
        help=(
            "Minimum length of a GBIF description "
            "to be downloaded"
        ),
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

    languages = [
        sanitize_component(language)
        for language in args.languages
    ]

    session = create_session()

    dataset_cache = {}

    errors = 0
    for species in species_list:
        errors += process_species(
            session,
            species,
            args.sources,
            languages,
            args.gbif_limit,
            args.gbif_min_chars,
            dataset_cache,
        )

    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
