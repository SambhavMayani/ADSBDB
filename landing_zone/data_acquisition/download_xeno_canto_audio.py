"""Acquire raw Xeno-canto recordings for EcoSentinel without modifying Landing.

Usage from the repository root:
    python landing_zone/data_acquisition/download_xeno_canto_audio.py --limit 4

Requires XENO_CANTO_API_KEY in the environment or untracked .env file.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from orchestration.files import atomic_json_write
from urllib.parse import urlparse

import requests
import yaml
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = 'https://xeno-canto.org/api/3/recordings'
SOURCE_NAME = 'xeno_canto'
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPECIES_CONFIG = PROJECT_ROOT / 'config' / 'species.yaml'
OUTPUT_ROOT = PROJECT_ROOT / 'data' / 'raw_dataset' / 'audio'
REQUEST_DELAY_SECONDS = 0.5
MAX_FILE_BYTES = 30 * 1024 * 1024
MIN_FILE_BYTES = 1024
ALLOWED_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a'}


def create_session():
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET'],
        respect_retry_after_header=True,
    )
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.headers.update(
        {'User-Agent': 'EcoSentinel-ADSDB/1.0 (academic audio data acquisition)'}
    )
    return session


def load_species():
    with SPECIES_CONFIG.open(encoding='utf-8') as f:
        return yaml.safe_load(f)['species']


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save_metadata(path, records):
    """Publish a complete registry atomically; preserve the previous one on failure."""
    atomic_json_write(path, records)


def read_metadata(path, directory, species_id):
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise ValueError(f'Expected an array in {path}; refusing to overwrite metadata')
    valid = []
    for record in records:
        if not isinstance(record, dict):
            continue
        filename = record.get('local_filename')
        if (
            record.get('species_id') == species_id
            and record.get('source_name') == SOURCE_NAME
            and isinstance(filename, str)
            and Path(filename).name == filename
            and (directory / filename).is_file()
            and (directory / filename).stat().st_size >= MIN_FILE_BYTES
        ):
            valid.append(record)
    return valid


def get_candidates(session, api_key, scientific_name, page):
    # Query genus and specific epithet explicitly to avoid partial name matches.
    genus, epithet = scientific_name.split()[:2]
    response = session.get(
        API_URL,
        params={'query': f'gen:"{genus}" sp:"{epithet}"', 'page': page, 'key': api_key},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload.get('recordings'), list):
        raise ValueError('Unexpected Xeno-canto response: missing recordings array')
    return payload


def extension_for(record):
    url = record.get('file') or ''
    original_name = record.get('file-name') or ''
    extension = (
        Path(urlparse(original_name).path).suffix.lower() or Path(urlparse(url).path).suffix.lower()
    )
    # Some API links have no extension even though the served file is MP3.
    return extension if extension in ALLOWED_EXTENSIONS else '.mp3'


def is_probably_audio(path, extension):
    if path.stat().st_size < MIN_FILE_BYTES:
        return False
    with path.open('rb') as f:
        signature = f.read(16)
    if signature.startswith((b'ID3', b'fLaC', b'OggS', b'RIFF')):
        return True
    if extension == '.mp3' and len(signature) >= 2:
        return signature[0] == 0xFF and (signature[1] & 0xE0) == 0xE0
    if extension == '.m4a' and b'ftyp' in signature[:12]:
        return True
    return False


def download_audio(session, url, target):
    tmp = target.with_name(target.name + '.part')
    try:
        with session.get(url, stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            total = 0
            with tmp.open('wb') as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        total += len(chunk)
                        if total > MAX_FILE_BYTES:
                            raise ValueError('Audio exceeded size limit')
                        f.write(chunk)
        if not is_probably_audio(tmp, target.suffix.lower()):
            raise ValueError('Downloaded file does not appear to be valid audio')
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)


def build_record(species, item, filename, path):
    rid = str(item['id'])
    return {
        'local_filename': filename,
        'source_name': SOURCE_NAME,
        'species_id': species['id'],
        'scientific_name': species['scientific_name'],
        'source_record_id': rid,
        'source_url': item.get('url') or f'https://xeno-canto.org/{rid}',
        'original_filename': item.get('file-name'),
        'recordist': item.get('rec'),
        'license': item.get('lic'),
        'duration': item.get('length'),
        'country': item.get('cnt'),
        'location': item.get('loc'),
        'type': item.get('type'),
        'quality': item.get('q'),
        'file_size_bytes': path.stat().st_size,
        'sha256': sha256_file(path),
    }


def process_species(session, api_key, species, limit, max_pages):
    species_id = species['id']
    folder = OUTPUT_ROOT / species_id
    folder.mkdir(parents=True, exist_ok=True)
    metadata_path = folder / '_metadata.json'
    records = read_metadata(metadata_path, folder, species_id)
    seen = {str(r.get('source_record_id')) for r in records if r.get('source_record_id')}
    print(f'\n{species_id}: {len(records)} existing, target {limit}')
    if len(records) >= limit:
        return len(records)

    for page in range(1, max_pages + 1):
        try:
            payload = get_candidates(session, api_key, species['scientific_name'], page)
        except (requests.RequestException, ValueError) as error:
            print(f'  Query failed for page {page}: {error}')
            break
        candidates = payload['recordings']
        if not candidates:
            break
        for item in candidates:
            if len(records) >= limit:
                break
            rid = str(item.get('id', ''))
            url = item.get('file')
            if not rid or not rid.isdigit() or not url or rid in seen:
                continue
            parsed_url = urlparse(url if not url.startswith('//') else 'https:' + url)
            if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
                continue
            # Verify the response belongs to the exact requested species.
            genus, _, epithet = species['scientific_name'].partition(' ')
            if (
                item.get('gen', '').casefold() != genus.casefold()
                or item.get('sp', '').casefold() != epithet.casefold()
            ):
                continue
            extension = extension_for(item)
            filename = f'xc_{rid}{extension}'
            target = folder / filename
            try:
                if not target.exists() or not is_probably_audio(target, extension):
                    download_audio(session, parsed_url.geturl(), target)
                record = build_record(species, item, filename, target)
                records.append(record)
                seen.add(rid)
                save_metadata(metadata_path, records)
                print(f'  Added {filename} ({len(records)}/{limit})')
            except (OSError, requests.RequestException, ValueError) as error:
                print(f'  Skipped XC{rid}: {error}')
                if target.exists() and not is_probably_audio(target, extension):
                    target.unlink(missing_ok=True)
            time.sleep(REQUEST_DELAY_SECONDS)
        if len(records) >= limit:
            break
        try:
            if page >= int(payload.get('numPages', page)):
                break
        except (ValueError, TypeError):
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    save_metadata(metadata_path, records)
    print(f'  Result: {len(records)}/{limit}')
    return len(records)


def main():
    parser = argparse.ArgumentParser(description='Download raw Xeno-canto wildlife recordings')
    parser.add_argument('--species', help='Single species ID from config/species.yaml')
    parser.add_argument('--limit', type=int, default=4, help='Target recordings per species')
    parser.add_argument(
        '--max-pages', type=int, default=10, help='Maximum API result pages per species'
    )
    args = parser.parse_args()
    if args.limit < 1 or args.max_pages < 1:
        parser.error('--limit and --max-pages must be positive')
    load_dotenv(PROJECT_ROOT / '.env')
    api_key = os.getenv('XENO_CANTO_API_KEY')
    if not api_key:
        parser.error('Set XENO_CANTO_API_KEY in your environment or untracked .env')
    species_list = load_species()
    if args.species:
        species_list = [s for s in species_list if s['id'] == args.species]
        if not species_list:
            parser.error(f'Unknown species: {args.species}')
    session = create_session()
    total = sum(
        process_species(session, api_key, s, args.limit, args.max_pages) for s in species_list
    )
    print(f'\nRegistered audio files: {total}; target: {len(species_list) * args.limit}')
    if total < len(species_list) * args.limit:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
