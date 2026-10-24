"""
Formatted Zone - audio homogenization.

Reads every audio object stored in Persistent Landing, converts it into the
canonical EcoSentinel audio representation and stores the new version in the
formatted-zone bucket, replicating the Persistent Landing folder structure:

    landing-zone/persistent_landing/audio/<species_id>/<name>.<any audio ext>
    -> formatted-zone/audio/<species_id>/<name>.flac

Canonical representation:
    codec / container : FLAC (lossless)
    sample format     : 16-bit signed PCM
    streams           : first audio stream only (embedded cover art, video,
                        subtitle and data streams are dropped)
    container tags    : removed (provenance travels in the object metadata)
    sample rate and channel layout are preserved, because resampling or
    downmixing are model-specific decisions for later zones.

Accepted inputs: MP3, WAV, FLAC, OGG/Vorbis, Opus, M4A/MP4/AAC, WMA, AIFF,
WebM/Matroska, AMR, CAF and AC3. Xeno-canto currently delivers mostly MP3, but
every format is supported so that new sources do not require code changes.

Decoding uses ffmpeg (system PATH, FFMPEG_BINARY or the imageio-ffmpeg wheel).
If ffmpeg is unavailable, libsndfile (soundfile) is used for the formats it
can decode natively.

Usage from the repository root:
    python formatted_zone/format_audio.py
    python formatted_zone/format_audio.py --dry-run
    python formatted_zone/format_audio.py --species bubo_bubo --max-items 2
"""

import argparse
import sys
import io
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import soundfile
from botocore.exceptions import ClientError


# ---------------------------------------------------------
# Storage configuration
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

LANDING_BUCKET = os.getenv('ECOSENTINEL_LANDING_BUCKET', 'landing-zone')
PERSISTENT_PREFIX = 'persistent_landing/'

FORMATTED_BUCKET = os.getenv('ECOSENTINEL_FORMATTED_BUCKET', 'formatted-zone')

MODALITY = 'audio'


# ---------------------------------------------------------
# Canonical audio format
# ---------------------------------------------------------

CANONICAL_EXTENSION = '.flac'
CANONICAL_CONTENT_TYPE = 'audio/flac'
CANONICAL_FORMAT_LABEL = 'flac_pcm16'
CANONICAL_SOUNDFILE_FORMAT = 'FLAC'
CANONICAL_SOUNDFILE_SUBTYPE = 'PCM_16'

FORMATTER_VERSION = '1.0'

FFMPEG_TIMEOUT_SECONDS = 300

# File extension -> source format label.
SUPPORTED_EXTENSIONS = {
    '.mp3': 'mp3',
    '.wav': 'wav',
    '.wave': 'wav',
    '.flac': 'flac',
    '.ogg': 'ogg',
    '.oga': 'ogg',
    '.opus': 'opus',
    '.m4a': 'm4a',
    '.mp4': 'm4a',
    '.aac': 'aac',
    '.wma': 'wma',
    '.aif': 'aiff',
    '.aiff': 'aiff',
    '.aifc': 'aiff',
    '.webm': 'webm',
    '.mka': 'matroska',
    '.amr': 'amr',
    '.caf': 'caf',
    '.ac3': 'ac3',
}

# Formats libsndfile can decode without ffmpeg. MP3 support depends on the
# libsndfile version bundled with soundfile, so it is checked at runtime.
SOUNDFILE_DECODABLE = {
    'wav',
    'flac',
    'ogg',
    'opus',
    'aiff',
    'caf',
}

if 'MP3' in soundfile.available_formats():
    SOUNDFILE_DECODABLE.add('mp3')

# Persistent metadata copied to the Formatted object for traceability.
PROPAGATED_METADATA_FIELDS = (
    'modality',
    'species_id',
    'source_name',
    'asset_hash',
    'ingestion_timestamp',
    'original_filename_encoded',
)


# ---------------------------------------------------------
# MinIO connection
# ---------------------------------------------------------


def create_minio_client():
    """Use the common lazy S3 client with bounded timeouts and retries."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from orchestration.storage import create_client

    return create_client()


def ensure_bucket_exists(client, bucket):
    try:
        client.head_bucket(Bucket=bucket)

    except ClientError as error:
        raise RuntimeError(
            f"Bucket '{bucket}' is not available. Run orchestration/initialize_storage.py first."
        ) from error


def object_exists(client, bucket, key):
    try:
        client.head_object(
            Bucket=bucket,
            Key=key,
        )
        return True

    except ClientError as error:
        error_code = error.response.get(
            'Error',
            {},
        ).get('Code')

        if error_code in {
            '404',
            'NoSuchKey',
            'NotFound',
        }:
            return False

        raise


def get_existing_formatted(client, bucket, key):
    """Return destination headers or None; propagate unexpected S3 failures."""
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = error.response.get('Error', {}).get('Code')
        if code in {'404', 'NoSuchKey', 'NotFound'}:
            return None
        raise


def verify_existing_formatted(persistent_key, formatted_key, head):
    """Never silently reuse another source or incompatible formatter output."""
    metadata = head.get('Metadata', {})
    if (
        unquote(metadata.get('source_persistent_key_encoded', '')) != persistent_key
        or metadata.get('canonical_format') != CANONICAL_FORMAT_LABEL
        or metadata.get('formatter_version') != FORMATTER_VERSION
        or head.get('ContentType') != CANONICAL_CONTENT_TYPE
        or head.get('ContentLength', 0) <= 0
    ):
        raise ValueError(
            f'Existing formatted output conflicts with lineage or policy: {formatted_key}'
        )


def list_persistent_audio(client, species_id=None):
    """
    List Persistent Landing audio objects, optionally for one species.
    Pagination keeps this working as the dataset grows.
    """

    prefix = f'{PERSISTENT_PREFIX}{MODALITY}/'

    if species_id:
        prefix += f'{species_id}/'

    paginator = client.get_paginator('list_objects_v2')

    keys = []

    for page in paginator.paginate(
        Bucket=LANDING_BUCKET,
        Prefix=prefix,
    ):
        for item in page.get('Contents', []):
            if not item['Key'].endswith('/'):
                keys.append(item['Key'])

    return sorted(keys)


# ---------------------------------------------------------
# Key mapping
# ---------------------------------------------------------


def build_formatted_key(persistent_key):
    """
    Replicate the Persistent structure and swap the extension:

    persistent_landing/audio/<species>/<stem>.<ext>
    -> audio/<species>/<stem>.flac
    """

    if not persistent_key.startswith(PERSISTENT_PREFIX):
        raise ValueError(f'Unexpected Persistent key: {persistent_key}')

    relative = PurePosixPath(persistent_key[len(PERSISTENT_PREFIX) :])

    if len(relative.parts) != 3 or relative.parts[0] != MODALITY:
        raise ValueError(f'Unexpected Persistent key layout: {persistent_key}')

    return str(relative.with_suffix(CANONICAL_EXTENSION))


# ---------------------------------------------------------
# Source format detection
# ---------------------------------------------------------


def sniff_audio_format(data):
    """
    Identify the container from its magic bytes. Content is trusted over the
    file extension, which may be wrong (Xeno-canto links without extension
    are stored as .mp3, for example).
    """

    head = data[:64]

    if head.startswith(b'ID3'):
        return 'mp3'

    if head[:4] == b'RIFF' and head[8:12] == b'WAVE':
        return 'wav'

    if head.startswith(b'fLaC'):
        return 'flac'

    if head.startswith(b'OggS'):
        return 'opus' if b'OpusHead' in head else 'ogg'

    if head[:4] == b'FORM' and head[8:12] in {b'AIFF', b'AIFC'}:
        return 'aiff'

    if head[4:8] == b'ftyp':
        return 'm4a'

    if head.startswith(b'\x1a\x45\xdf\xa3'):
        return 'matroska'

    if head.startswith(b'\x30\x26\xb2\x75\x8e\x66\xcf\x11'):
        return 'wma'

    if head.startswith(b'#!AMR'):
        return 'amr'

    if head.startswith(b'caff'):
        return 'caf'

    if head.startswith(b'\x0b\x77'):
        return 'ac3'

    # MPEG frame sync (11 set bits). ADTS AAC shares the sync word but
    # uses layer bits 00, while MP3 never does.
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return 'aac' if (head[1] & 0x06) == 0 else 'mp3'

    return None


def detect_source_format(data, extension):
    sniffed = sniff_audio_format(data)
    from_extension = SUPPORTED_EXTENSIONS.get(extension.lower())

    source_format = sniffed or from_extension

    if not source_format:
        raise ValueError(
            f"Unsupported or unrecognized audio format (extension '{extension or 'none'}')"
        )

    return source_format


# ---------------------------------------------------------
# Conversion
# ---------------------------------------------------------


def resolve_ffmpeg():
    """
    Locate an ffmpeg executable: FFMPEG_BINARY, system PATH, or the binary
    shipped with the imageio-ffmpeg package.
    """

    configured = os.getenv('FFMPEG_BINARY')

    if configured and Path(configured).is_file():
        return configured

    found = shutil.which('ffmpeg')

    if found:
        return found

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()

    except (ImportError, RuntimeError):
        return None


def convert_with_ffmpeg(ffmpeg, data, extension):
    """
    Transcode any ffmpeg-readable audio into FLAC / 16-bit PCM.

    Temporary files are used instead of pipes because MP4/M4A containers may
    store their index at the end of the file and need a seekable input.
    """

    with tempfile.TemporaryDirectory() as tmp:
        source_path = Path(tmp) / f'input{extension or ".bin"}'
        target_path = Path(tmp) / f'output{CANONICAL_EXTENSION}'

        source_path.write_bytes(data)

        command = [
            ffmpeg,
            '-hide_banner',
            '-loglevel',
            'error',
            '-nostdin',
            '-y',
            '-i',
            str(source_path),
            # First audio stream only: drops cover art and other streams.
            '-map',
            '0:a:0',
            '-map_metadata',
            '-1',
            '-map_chapters',
            '-1',
            '-c:a',
            'flac',
            '-sample_fmt',
            's16',
            # Request deterministic encoding when supported by this ffmpeg build.
            # PCM_16 can quantize higher-precision input samples.
            '-flags',
            '+bitexact',
            '-fflags',
            '+bitexact',
            str(target_path),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )

        if result.returncode != 0 or not target_path.exists():
            message = result.stderr.decode(
                'utf-8',
                errors='replace',
            ).strip()

            raise RuntimeError(f'ffmpeg conversion failed: {message[-500:]}')

        return target_path.read_bytes()


def convert_with_soundfile(data):
    """
    Fallback converter based on libsndfile for formats it decodes natively.
    """

    with soundfile.SoundFile(io.BytesIO(data)) as source:
        samples = source.read(
            dtype='int16',
            always_2d=True,
        )
        sample_rate = source.samplerate

    buffer = io.BytesIO()

    soundfile.write(
        buffer,
        samples,
        sample_rate,
        format=CANONICAL_SOUNDFILE_FORMAT,
        subtype=CANONICAL_SOUNDFILE_SUBTYPE,
    )

    return buffer.getvalue()


def convert_audio(data, extension, decoder='auto', ffmpeg=None):
    """
    Convert raw audio bytes into canonical FLAC bytes.

    Returns (flac_bytes, source_format, decoder_used).
    """

    source_format = detect_source_format(
        data,
        extension,
    )

    use_ffmpeg = decoder in {'auto', 'ffmpeg'} and ffmpeg
    soundfile_allowed = decoder in {'auto', 'soundfile'} and source_format in SOUNDFILE_DECODABLE

    if decoder == 'ffmpeg' and not ffmpeg:
        raise RuntimeError('ffmpeg decoder requested but no ffmpeg executable was found')

    if use_ffmpeg:
        try:
            return (
                convert_with_ffmpeg(ffmpeg, data, extension),
                source_format,
                'ffmpeg',
            )

        except (RuntimeError, subprocess.TimeoutExpired):
            if not soundfile_allowed:
                raise

    if soundfile_allowed:
        return (
            convert_with_soundfile(data),
            source_format,
            'soundfile',
        )

    raise RuntimeError(
        f"Cannot decode '{source_format}' without ffmpeg. Install ffmpeg "
        'or the imageio-ffmpeg package (see requirements.txt).'
    )


def inspect_canonical_audio(flac_bytes):
    """
    Verify that the produced bytes really are canonical FLAC / PCM_16 and
    return technical properties stored as object metadata.
    """

    info = soundfile.info(io.BytesIO(flac_bytes))

    if info.format != CANONICAL_SOUNDFILE_FORMAT or info.subtype != CANONICAL_SOUNDFILE_SUBTYPE:
        raise RuntimeError(f'Converted audio is not canonical: {info.format}/{info.subtype}')

    if info.frames <= 0:
        raise RuntimeError('Converted audio contains no samples')

    return {
        'sample_rate': info.samplerate,
        'channels': info.channels,
        'frames': info.frames,
        'duration_seconds': round(info.duration, 3),
    }


# ---------------------------------------------------------
# Formatted metadata
# ---------------------------------------------------------


def validate_persistent_metadata(metadata, persistent_key=None):
    """Validate required lineage, modality, and optional key/path consistency."""
    for field in ('modality', 'species_id', 'source_name', 'asset_hash'):
        value = metadata.get(field)

        if not isinstance(value, str) or not value.strip() or value.strip().lower() == 'unknown':
            raise ValueError(f"Missing or invalid Persistent metadata '{field}'")

    if metadata['modality'] != MODALITY:
        raise ValueError(f"Object modality is '{metadata['modality']}', expected '{MODALITY}'")

    if persistent_key is not None:
        expected_species = PurePosixPath(persistent_key).parent.name
        if metadata['species_id'] != expected_species:
            raise ValueError(
                f"Species mismatch for '{persistent_key}': metadata='{metadata['species_id']}'"
            )


def build_formatted_metadata(
    persistent_key,
    persistent_metadata,
    source_format,
    decoder,
    audio_info,
):
    """
    S3 metadata travels as HTTP headers, so every value must be ASCII.
    """

    metadata = {
        field: persistent_metadata[field]
        for field in PROPAGATED_METADATA_FIELDS
        if persistent_metadata.get(field)
    }

    metadata.update(
        {
            'source_persistent_key_encoded': quote(
                persistent_key,
                safe='',
            ),
            'source_format': source_format,
            'original_format': source_format,
            'canonical_format': CANONICAL_FORMAT_LABEL,
            'formatted_format': 'flac',
            'format_version': FORMATTER_VERSION,
            'decoder': decoder,
            'sample_rate': str(audio_info['sample_rate']),
            'channels': str(audio_info['channels']),
            'frames': str(audio_info['frames']),
            'duration_seconds': str(audio_info['duration_seconds']),
            'formatted_timestamp': datetime.now(timezone.utc).isoformat(),
            'formatter_version': FORMATTER_VERSION,
        }
    )

    metadata['formatted_at'] = metadata['formatted_timestamp']
    return metadata


# ---------------------------------------------------------
# Processing
# ---------------------------------------------------------


def format_object(client, persistent_key, formatted_key, decoder, ffmpeg):
    """Read Persistent, validate, convert, verify bytes, upload and check size."""

    response = client.get_object(
        Bucket=LANDING_BUCKET,
        Key=persistent_key,
    )

    persistent_metadata = response.get('Metadata', {})

    body = response['Body']
    try:
        validate_persistent_metadata(persistent_metadata, persistent_key)
        data = body.read()
    finally:
        body.close()

    flac_bytes, source_format, decoder_used = convert_audio(
        data,
        PurePosixPath(persistent_key).suffix,
        decoder=decoder,
        ffmpeg=ffmpeg,
    )

    audio_info = inspect_canonical_audio(flac_bytes)

    client.put_object(
        Bucket=FORMATTED_BUCKET,
        Key=formatted_key,
        Body=flac_bytes,
        ContentType=CANONICAL_CONTENT_TYPE,
        Metadata=build_formatted_metadata(
            persistent_key,
            persistent_metadata,
            source_format,
            decoder_used,
            audio_info,
        ),
    )

    stored = client.head_object(
        Bucket=FORMATTED_BUCKET,
        Key=formatted_key,
    )

    if stored['ContentLength'] != len(flac_bytes):
        raise RuntimeError(f'Formatted object verification failed: {formatted_key}')

    return source_format, decoder_used, audio_info


def process_audio(
    species_id=None,
    max_items=None,
    dry_run=False,
    force=False,
    decoder='auto',
):
    client = create_minio_client()

    ensure_bucket_exists(client, LANDING_BUCKET)
    ensure_bucket_exists(client, FORMATTED_BUCKET)

    ffmpeg = resolve_ffmpeg() if decoder != 'soundfile' else None

    print(f'ffmpeg: {ffmpeg or "not found (soundfile fallback only)"}')

    persistent_keys = list_persistent_audio(client, species_id)

    print(f'Persistent audio objects found: {len(persistent_keys)}')
    print()

    formatted_count = 0
    planned_count = 0
    skipped_count = 0
    error_count = 0

    for persistent_key in persistent_keys:
        if max_items is not None and formatted_count + planned_count >= max_items:
            break

        try:
            formatted_key = build_formatted_key(persistent_key)
            persistent_head = client.head_object(
                Bucket=LANDING_BUCKET,
                Key=persistent_key,
            )
            validate_persistent_metadata(
                persistent_head.get('Metadata', {}),
                persistent_key,
            )

            print(f'PERSISTENT: {persistent_key}')
            print(f'FORMATTED:  {FORMATTED_BUCKET}/{formatted_key}')

            existing = get_existing_formatted(client, FORMATTED_BUCKET, formatted_key)
            if existing is not None and not force:
                verify_existing_formatted(persistent_key, formatted_key, existing)
                print('ACTION:     ALREADY FORMATTED (lineage verified)')
                print('-' * 70)
                skipped_count += 1
                continue

            if dry_run:
                print('ACTION:     DRY RUN')
                print('-' * 70)
                planned_count += 1
                continue

            source_format, decoder_used, audio_info = format_object(
                client,
                persistent_key,
                formatted_key,
                decoder,
                ffmpeg,
            )

            print(
                f'ACTION:     {source_format} -> {CANONICAL_FORMAT_LABEL} '
                f'via {decoder_used} '
                f'({audio_info["sample_rate"]} Hz, '
                f'{audio_info["channels"]} ch, '
                f'{audio_info["duration_seconds"]} s)'
            )
            print('-' * 70)

            formatted_count += 1

        except Exception as error:
            error_count += 1

            print(f'ERROR: {persistent_key}')
            print(f'       {error}')
            print('-' * 70)

    print()
    print('=' * 70)
    print('Audio Formatted Zone processing completed')
    print(f'Formatted:          {formatted_count}')
    print(f'Already formatted:  {skipped_count}')
    print(f'Planned:            {planned_count}')
    print(f'Errors:             {error_count}')
    print('=' * 70)

    return error_count


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Homogenize Persistent Landing audio into canonical '
            'FLAC (16-bit PCM) objects in the Formatted Zone.'
        )
    )

    parser.add_argument(
        '--species',
        help='Only process one species id',
    )

    parser.add_argument(
        '--max-items',
        type=int,
        default=None,
        help='Maximum number of objects to format',
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show planned operations without writing objects',
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Reformat objects that already exist in the Formatted Zone',
    )

    parser.add_argument(
        '--decoder',
        choices=('auto', 'ffmpeg', 'soundfile'),
        default='auto',
        help='Audio decoding backend (default: ffmpeg with soundfile fallback)',
    )

    args = parser.parse_args()
    if args.max_items is not None and args.max_items < 1:
        parser.error('--max-items must be greater than zero')

    errors = process_audio(
        species_id=args.species,
        max_items=args.max_items,
        dry_run=args.dry_run,
        force=args.force,
        decoder=args.decoder,
    )

    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
