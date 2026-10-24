"""
Formatted Zone - text homogenization.

Reads every text object stored in Persistent Landing, extracts its textual
content and stores it in the canonical EcoSentinel text representation in the
formatted-zone bucket, replicating the Persistent Landing folder structure:

    landing-zone/persistent_landing/text/<species_id>/<name>.<any text ext>
    -> formatted-zone/text/<species_id>/<name>.txt

Canonical representation (syntactic only, no content cleaning):
    plain text, UTF-8 without BOM, LF line endings, Unicode NFC, no control
    characters other than tab/newline, exactly one trailing newline.

Accepted inputs:
    .txt .text           decoded and normalized
    .md .markdown        markup syntax removed
    .html .htm .xhtml    visible text extracted (scripts/styles dropped)
    .xml                 element text extracted
    .json                hybrid extraction (priority keys + longest string)
    .jsonl .ndjson       hybrid extraction per line
    .pdf                 embedded text layer extracted (pypdf)
    .docx                paragraph text extracted (Office Open XML)
    .odt                 paragraph text extracted (OpenDocument)

Whitespace standardization, casing, deduplication and other quality steps
belong to the Trusted Zone.

Usage from the repository root:
    python formatted_zone/format_text.py
    python formatted_zone/format_text.py --dry-run
    python formatted_zone/format_text.py --species lynx_pardinus --max-items 3
"""

import argparse
import sys
import io
import json
import os
import re
import unicodedata
import zipfile
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote
from xml.etree import ElementTree

from botocore.exceptions import ClientError


# ---------------------------------------------------------
# Storage configuration
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

LANDING_BUCKET = os.getenv('ECOSENTINEL_LANDING_BUCKET', 'landing-zone')
PERSISTENT_PREFIX = 'persistent_landing/'

FORMATTED_BUCKET = os.getenv('ECOSENTINEL_FORMATTED_BUCKET', 'formatted-zone')

MODALITY = 'text'


# ---------------------------------------------------------
# Canonical text format
# ---------------------------------------------------------

CANONICAL_EXTENSION = '.txt'
CANONICAL_CONTENT_TYPE = 'text/plain; charset=utf-8'
CANONICAL_FORMAT_LABEL = 'txt_utf8_lf_nfc'

FORMATTER_VERSION = '1.0'

# File extension -> source format label.
SUPPORTED_EXTENSIONS = {
    '.txt': 'txt',
    '.text': 'txt',
    '.md': 'markdown',
    '.markdown': 'markdown',
    '.html': 'html',
    '.htm': 'html',
    '.xhtml': 'html',
    '.xml': 'xml',
    '.json': 'json',
    '.jsonl': 'jsonl',
    '.ndjson': 'jsonl',
    '.pdf': 'pdf',
    '.docx': 'docx',
    '.odt': 'odt',
}

# JSON keys that conventionally hold the main text of a document, in order
# of preference. Matching is case-insensitive.
JSON_PRIORITY_KEYS = (
    'text',
    'content',
    'body',
    'description',
    'summary',
    'extract',
    'abstract',
    'plot',
    'caption',
    'transcript',
    'article',
    'message',
)

# S3 metadata travels in HTTP headers (about 2 KB in total).
MAX_METADATA_VALUE_LENGTH = 256

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


def list_persistent_text(client, species_id=None):
    """
    List Persistent Landing text objects, optionally for one species.
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
    persistent_landing/text/<species>/<stem>.<ext>
    -> text/<species>/<stem>.txt
    """

    if not persistent_key.startswith(PERSISTENT_PREFIX):
        raise ValueError(f'Unexpected Persistent key: {persistent_key}')

    relative = PurePosixPath(persistent_key[len(PERSISTENT_PREFIX) :])

    if len(relative.parts) != 3 or relative.parts[0] != MODALITY:
        raise ValueError(f'Unexpected Persistent key layout: {persistent_key}')

    return str(relative.with_suffix(CANONICAL_EXTENSION))


# ---------------------------------------------------------
# Decoding and canonical normalization
# ---------------------------------------------------------


def decode_bytes(data):
    """
    Decode raw bytes into str.

    Order: explicit BOM, strict UTF-8, strict Windows-1252, charset detection
    (charset-normalizer, installed with requests) and finally Latin-1, which
    can decode any byte sequence.

    Windows-1252 is tried before statistical detection because the sources
    are Spanish/English and detectors often mistake short Western European
    texts for Central European code pages (e.g. "ñ" decoded as "ń").

    Returns (text, encoding_label).
    """

    boms = (
        (b'\xef\xbb\xbf', 'utf-8-sig'),
        (b'\xff\xfe\x00\x00', 'utf-32'),
        (b'\x00\x00\xfe\xff', 'utf-32'),
        (b'\xff\xfe', 'utf-16'),
        (b'\xfe\xff', 'utf-16'),
    )

    for bom, encoding in boms:
        if data.startswith(bom):
            return data.decode(encoding), encoding

    try:
        return data.decode('utf-8'), 'utf-8'

    except UnicodeDecodeError:
        pass

    try:
        return data.decode('cp1252'), 'cp1252'

    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()

        if best is not None:
            return str(best), best.encoding

    except ImportError:
        pass

    return data.decode('latin-1'), 'latin-1'


CONTROL_CHARACTERS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def to_canonical_text(text):
    """
    Apply the canonical text representation. This is a syntactic
    normalization only: words, punctuation and spacing are preserved.
    """

    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = unicodedata.normalize('NFC', text)
    text = text.lstrip('\ufeff')
    text = CONTROL_CHARACTERS.sub('', text)
    text = text.rstrip('\n')

    return f'{text}\n'


def collapse_layout_whitespace(text):
    """
    Used only for markup formats (HTML, XML, PDF, ...), where source
    whitespace is layout rather than content.
    """

    lines = [re.sub(r'[ \t\f\v\u00a0]+', ' ', line).strip() for line in text.split('\n')]

    text = '\n'.join(lines)

    return re.sub(r'\n{3,}', '\n\n', text).strip()


# ---------------------------------------------------------
# HTML / XML / Markdown
# ---------------------------------------------------------


class VisibleTextParser(HTMLParser):
    """
    Collect visible text from HTML, inserting line breaks at block-level
    elements and ignoring non-content elements.
    """

    SKIPPED_TAGS = {
        'script',
        'style',
        'noscript',
        'template',
        'head',
        'svg',
    }

    BLOCK_TAGS = {
        'address',
        'article',
        'aside',
        'blockquote',
        'br',
        'dd',
        'div',
        'dl',
        'dt',
        'figcaption',
        'figure',
        'footer',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
        'header',
        'hr',
        'li',
        'main',
        'nav',
        'ol',
        'p',
        'pre',
        'section',
        'table',
        'tr',
        'td',
        'th',
        'ul',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIPPED_TAGS:
            self.skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append('\n')

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIPPED_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in self.BLOCK_TAGS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(markup):
    parser = VisibleTextParser()
    parser.feed(markup)
    parser.close()

    return collapse_layout_whitespace(''.join(parser.parts))


def looks_like_html(text):
    return bool(
        re.search(
            r'</?(p|div|br|span|b|i|em|strong|a|ul|ol|li|h[1-6]|table)\b[^>]*>',
            text,
            flags=re.IGNORECASE,
        )
    )


def xml_to_text(markup):
    # Python's expat parser refuses entity-expansion attacks by default.
    root = ElementTree.fromstring(markup)

    return collapse_layout_whitespace(
        '\n'.join(fragment.strip() for fragment in root.itertext() if fragment.strip())
    )


def markdown_to_text(markdown):
    """
    Remove the most common Markdown syntax while keeping the prose.
    """

    text = re.sub(r'^```.*?$', '', markdown, flags=re.MULTILINE)
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    # [ \t] instead of \s so that blank lines between blocks are kept.
    text = re.sub(r'^[ \t]{0,3}#{1,6}[ \t]*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[ \t]{0,3}>[ \t]?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[ \t]*([-*+]|\d+\.)[ \t]+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[ \t]*([-*_][ \t]*){3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(\*\*|__)(.+?)\1', r'\2', text)
    text = re.sub(r'(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])', r'\2', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    return text


# ---------------------------------------------------------
# JSON: hybrid extraction (priority keys + longest string)
# ---------------------------------------------------------


def _string_value(value):
    """
    Accept a non-empty string, or a list made only of strings (for example
    a list of paragraphs), as a textual value.
    """

    if isinstance(value, str) and value.strip():
        return value

    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        joined = '\n\n'.join(item for item in value if item.strip())
        return joined or None

    return None


def find_priority_key(document):
    """
    Step 1 (deterministic): breadth-first search for a conventional text
    key. The shallowest match wins, because keys closer to the root describe
    the document itself rather than nested sub-records; at equal depth the
    order of JSON_PRIORITY_KEYS decides.

    Returns (path, text) or None.
    """

    priority = {key: index for index, key in enumerate(JSON_PRIORITY_KEYS)}

    queue = deque([(document, '$')])

    while queue:
        level_matches = []

        for _ in range(len(queue)):
            node, path = queue.popleft()

            if isinstance(node, dict):
                for key, value in node.items():
                    child_path = f'{path}.{key}'
                    rank = priority.get(str(key).lower())
                    text = _string_value(value)

                    if rank is not None and text:
                        level_matches.append((rank, child_path, text))

                    if isinstance(value, (dict, list)):
                        queue.append((value, child_path))

            elif isinstance(node, list):
                for index, value in enumerate(node):
                    if isinstance(value, (dict, list)):
                        queue.append((value, f'{path}[{index}]'))

        if level_matches:
            _, path, text = min(level_matches, key=lambda match: match[0])
            return path, text

    return None


def iter_strings(node, path='$'):
    """
    Recursively yield (path, value) for every string in a JSON structure.
    """

    if isinstance(node, str):
        yield path, node

    elif isinstance(node, dict):
        for key, value in node.items():
            yield from iter_strings(value, f'{path}.{key}')

    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_strings(value, f'{path}[{index}]')


def find_longest_string(document):
    """
    Step 2 (heuristic fallback for unknown schemas): the longest string in
    the document is assumed to be its main text.

    Returns (path, text) or None.
    """

    strings = [(path, value) for path, value in iter_strings(document) if value.strip()]

    if not strings:
        return None

    return max(strings, key=lambda item: len(item[1]))


def extract_json_text(document):
    """
    Hybrid extraction for one JSON document.

    Returns (text, method, json_path).
    """

    match = find_priority_key(document)

    if match:
        path, text = match
        method = 'json_priority_key'

    else:
        match = find_longest_string(document)

        if not match:
            raise ValueError('JSON document contains no text values')

        path, text = match
        method = 'json_longest_string'

    # Some APIs embed HTML inside JSON string fields.
    if looks_like_html(text):
        text = html_to_text(text)
        method += '+html'

    return text, method, path


def extract_json_records(records):
    """
    Apply the hybrid extraction to several JSON records (JSON array of
    records or JSON Lines) and join the results.
    """

    texts = []
    methods = set()

    for record in records:
        try:
            text, method, _ = extract_json_text(record)
        except ValueError:
            continue

        texts.append(text.strip())
        methods.add(method)

    if not texts:
        raise ValueError('No JSON record contains text values')

    return '\n\n'.join(texts), '+'.join(sorted(methods)), 'per_record'


def json_to_text(raw):
    document = json.loads(raw)

    # A top-level array of records/paragraphs is treated record by record.
    if (
        isinstance(document, list)
        and document
        and all(isinstance(item, (dict, list)) for item in document)
    ):
        return extract_json_records(document)

    return extract_json_text(document)


def jsonl_to_text(raw):
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]

    return extract_json_records(records)


# ---------------------------------------------------------
# Binary document formats
# ---------------------------------------------------------


def pdf_to_text(data):
    try:
        from pypdf import PdfReader

    except ImportError as error:
        raise RuntimeError(
            'PDF support requires the pypdf package (see requirements.txt)'
        ) from error

    reader = PdfReader(io.BytesIO(data))

    pages = [(page.extract_text() or '') for page in reader.pages]

    text = collapse_layout_whitespace('\n\n'.join(pages))

    if not text:
        raise ValueError('PDF has no extractable text layer (scanned PDFs need OCR)')

    return text


WORD_NAMESPACE = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def docx_to_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read('word/document.xml'))

    paragraphs = []

    for paragraph in root.iter(f'{WORD_NAMESPACE}p'):
        parts = []

        for node in paragraph.iter():
            if node.tag == f'{WORD_NAMESPACE}t' and node.text:
                parts.append(node.text)
            elif node.tag == f'{WORD_NAMESPACE}tab':
                parts.append('\t')
            elif node.tag in {f'{WORD_NAMESPACE}br', f'{WORD_NAMESPACE}cr'}:
                parts.append('\n')

        paragraphs.append(''.join(parts))

    return '\n'.join(paragraphs).strip()


ODF_TEXT_NAMESPACE = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'


def odt_to_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read('content.xml'))

    paragraphs = [
        ''.join(node.itertext())
        for node in root.iter()
        if node.tag in {f'{ODF_TEXT_NAMESPACE}p', f'{ODF_TEXT_NAMESPACE}h'}
    ]

    return '\n'.join(paragraphs).strip()


# ---------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------


def detect_source_format(data, extension):
    """
    The extension decides the parser; magic bytes override it for binary
    containers, which are unambiguous.
    """

    if data.startswith(b'%PDF-'):
        return 'pdf'

    if data.startswith(b'PK\x03\x04'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())

        if 'word/document.xml' in names:
            return 'docx'

        if 'content.xml' in names:
            return 'odt'

    source_format = SUPPORTED_EXTENSIONS.get(extension.lower())

    if not source_format:
        raise ValueError(f"Unsupported text format (extension '{extension or 'none'}')")

    return source_format


def convert_text(data, extension):
    """
    Convert raw bytes of any supported format into canonical text.

    Returns (canonical_text, details) where details documents how the text
    was obtained (stored as object metadata for traceability).
    """

    source_format = detect_source_format(data, extension)

    details = {
        'source_format': source_format,
        'source_encoding': 'binary',
        'extraction_method': source_format,
        'json_path': None,
    }

    if source_format == 'pdf':
        text = pdf_to_text(data)

    elif source_format == 'docx':
        text = docx_to_text(data)

    elif source_format == 'odt':
        text = odt_to_text(data)

    else:
        raw, encoding = decode_bytes(data)
        details['source_encoding'] = encoding

        if source_format == 'txt':
            text = raw

        elif source_format == 'markdown':
            text = markdown_to_text(raw)

        elif source_format == 'html':
            text = html_to_text(raw)

        elif source_format == 'xml':
            text = xml_to_text(raw)

        elif source_format == 'json':
            text, method, path = json_to_text(raw)
            details['extraction_method'] = method
            details['json_path'] = path

        elif source_format == 'jsonl':
            text, method, path = jsonl_to_text(raw)
            details['extraction_method'] = method
            details['json_path'] = path

        else:
            raise ValueError(f"No parser for '{source_format}'")

    canonical = to_canonical_text(text)

    if not canonical.strip():
        raise ValueError('No text content could be extracted')

    return canonical, details


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


def ascii_metadata_value(value):
    """URL-encode auxiliary metadata within the configured header limit.

    Avoid cutting a percent-escaped character halfway through its encoding.
    Long values are abbreviated; the original structured source remains in
    Persistent Landing.
    """
    encoded = quote(str(value), safe='$.[]_-:+')
    if len(encoded) <= MAX_METADATA_VALUE_LENGTH:
        return encoded

    shortened = encoded[: MAX_METADATA_VALUE_LENGTH - 1]
    # A final '%' or '%A' would be an incomplete percent escape.
    shortened = re.sub(r'%(?:[0-9A-F])?$', '', shortened)
    return shortened + '~'


def build_formatted_metadata(
    persistent_key,
    persistent_metadata,
    canonical_text,
    details,
):
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
            'source_format': details['source_format'],
            'original_format': details['source_format'],
            'formatted_format': 'txt',
            'format_version': FORMATTER_VERSION,
            'source_encoding': ascii_metadata_value(details['source_encoding']),
            'extraction_method': ascii_metadata_value(details['extraction_method']),
            'canonical_format': CANONICAL_FORMAT_LABEL,
            'char_count': str(len(canonical_text)),
            'formatted_timestamp': datetime.now(timezone.utc).isoformat(),
            'formatter_version': FORMATTER_VERSION,
        }
    )

    if details.get('json_path'):
        metadata['json_path_encoded'] = ascii_metadata_value(details['json_path'])

    metadata['formatted_at'] = metadata['formatted_timestamp']
    return metadata


# ---------------------------------------------------------
# Processing
# ---------------------------------------------------------


def format_object(client, persistent_key, formatted_key):
    """Read Persistent, validate, extract, upload and check stored size."""

    response = client.get_object(
        Bucket=LANDING_BUCKET,
        Key=persistent_key,
    )

    persistent_metadata = response.get('Metadata', {})

    body = response['Body']
    try:
        validate_persistent_metadata(persistent_metadata, persistent_key)
        raw_bytes = body.read()
    finally:
        body.close()

    canonical_text, details = convert_text(
        raw_bytes,
        PurePosixPath(persistent_key).suffix,
    )

    body = canonical_text.encode('utf-8')

    client.put_object(
        Bucket=FORMATTED_BUCKET,
        Key=formatted_key,
        Body=body,
        ContentType=CANONICAL_CONTENT_TYPE,
        Metadata=build_formatted_metadata(
            persistent_key,
            persistent_metadata,
            canonical_text,
            details,
        ),
    )

    stored = client.head_object(
        Bucket=FORMATTED_BUCKET,
        Key=formatted_key,
    )

    if stored['ContentLength'] != len(body):
        raise RuntimeError(f'Formatted object verification failed: {formatted_key}')

    return details, len(canonical_text)


def process_text(
    species_id=None,
    max_items=None,
    dry_run=False,
    force=False,
):
    client = create_minio_client()

    ensure_bucket_exists(client, LANDING_BUCKET)
    ensure_bucket_exists(client, FORMATTED_BUCKET)

    persistent_keys = list_persistent_text(client, species_id)

    print(f'Persistent text objects found: {len(persistent_keys)}')
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

            details, char_count = format_object(
                client,
                persistent_key,
                formatted_key,
            )

            print(
                f'ACTION:     {details["source_format"]} -> '
                f'{CANONICAL_FORMAT_LABEL} '
                f'[{details["extraction_method"]}'
                + (f' @ {details["json_path"]}' if details.get('json_path') else '')
                + f', {char_count} chars]'
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
    print('Text Formatted Zone processing completed')
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
            'Homogenize Persistent Landing text into canonical UTF-8 '
            'plain-text objects in the Formatted Zone.'
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

    args = parser.parse_args()
    if args.max_items is not None and args.max_items < 1:
        parser.error('--max-items must be greater than zero')

    errors = process_text(
        species_id=args.species,
        max_items=args.max_items,
        dry_run=args.dry_run,
        force=args.force,
    )

    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
