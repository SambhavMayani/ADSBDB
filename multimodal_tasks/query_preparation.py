"""Query-time preparation: the corpus processing reused in memory, never stored.

The indexed corpus passed through Formatted (canonical representation) and
Trusted (generic quality profiling) before Exploitation. External query inputs
must be comparable with those vectors, so this module calls the same zone
functions on the query bytes. It does not run the zone scripts, touch MinIO,
write files or add anything to the index.

Policy for queries, different from the corpus:
- Formatted conversions are applied exactly (JPEG RGB q95, FLAC PCM16, UTF-8 NFC).
- Trusted measurements are reused, but every corpus rejection or warning becomes
  a non-blocking user warning: a poor query still runs (poor query -> possibly
  poorer results), the user keeps the decision.
- An image already accepted in Trusted is not re-encoded: it is the canonical
  representation that was indexed.
- Audio is accepted only in formats the Formatted converter decodes in memory
  (libsndfile); formats needing ffmpeg would require temporary files on disk.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

from formatted_zone.format_audio import (
    SOUNDFILE_DECODABLE,
    convert_audio,
    detect_source_format,
)
from formatted_zone.format_images import SUPPORTED_IMAGE_FORMATS, convert_to_jpeg
from formatted_zone.format_text import to_canonical_text

# Image encodings accepted by the Formatted Zone (JPEG, PNG, WEBP, MPO, BMP, GIF, TIFF).
QUERY_IMAGE_FORMATS = frozenset(SUPPORTED_IMAGE_FORMATS)
# Audio containers the Formatted converter decodes without ffmpeg/temporary files.
QUERY_AUDIO_FORMATS = frozenset(SOUNDFILE_DECODABLE)

IMAGE_WARNINGS = {
    'low_sharpness': (
        'La imagen adjunta tiene baja nitidez, por lo que los resultados recuperados '
        'podrían ser menos precisos.'
    ),
    'low_brightness': (
        'La imagen adjunta es muy oscura, por lo que los resultados recuperados '
        'podrían ser menos precisos.'
    ),
    'monochrome_like': (
        'La imagen adjunta apenas tiene color; la similitud visual puede ser menos fiable.'
    ),
    'unusual_aspect_ratio': (
        'La imagen adjunta tiene una proporción poco habitual; '
        'el modelo visual podría captar peor su contenido.'
    ),
    'dimensions_too_small': (
        'La imagen adjunta es muy pequeña (menos de 128 px de lado); '
        'los resultados podrían ser menos precisos.'
    ),
}
AUDIO_WARNINGS = {
    'duration_below_minimum': (
        'El audio adjunto es extremadamente breve; los resultados podrían ser poco fiables.'
    ),
    'short_recording': 'El audio adjunto es muy breve; los resultados podrían ser menos precisos.',
    'digital_silence': 'El audio adjunto parece silencio; los resultados podrían no ser relevantes.',
    'low_rms': (
        'El audio adjunto tiene un nivel muy bajo; los resultados podrían ser menos precisos.'
    ),
    'many_low_energy_windows': (
        'La mayor parte del audio adjunto tiene muy poca energía; '
        'los resultados podrían ser menos precisos.'
    ),
    'possible_clipping': (
        'El audio adjunto parece saturado; los resultados podrían ser menos precisos.'
    ),
    'dc_offset': (
        'El audio adjunto presenta un desplazamiento de continua; '
        'los resultados podrían ser menos precisos.'
    ),
}


@dataclass(frozen=True)
class PreparedQuery:
    """Canonical in-memory bytes plus a small, displayable preparation report."""

    modality: str
    data: bytes
    report: dict = field(default_factory=dict)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _report(modality, raw, source_format, canonical, flags, warnings_map, metrics, steps):
    return {
        'modality': modality,
        'input_sha256': _sha256(raw),
        'source_format': source_format,
        'canonical_format': canonical,
        'steps': steps,
        'flags': flags,
        'warnings': [warnings_map[flag] for flag in flags if flag in warnings_map],
        'metrics': metrics,
        'persisted': False,
    }


def prepare_query_text(text: str) -> str:
    """Apply the Formatted text contract (UTF-8 NFC, LF, no control characters).

    Indexed chunks are stripped after tokenization, so the query is stripped too.
    Words, case and punctuation are preserved, as in the Formatted and Trusted zones.
    """
    if not isinstance(text, str):
        raise ValueError('Expected a text query')
    return to_canonical_text(text).strip()


def prepare_query_image(raw: bytes, *, already_canonical: bool = False) -> PreparedQuery:
    """Formatted JPEG conversion plus Trusted image measurements as warnings.

    `already_canonical=True` is for images read from the Trusted Zone: they were
    converted before indexing, so a JPEG is reused byte for byte and only the
    measurements are repeated (re-encoding would move it away from its vector).
    """
    from PIL import Image, UnidentifiedImageError

    from trusted_zone.quality.image_quality import analyze, image_rejection
    from trusted_zone.validate_images import load_policy

    if not isinstance(raw, bytes) or not raw:
        raise ValueError('Expected image bytes')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            source_format = image.format
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError('Unsupported or invalid image file') from exc
    if source_format not in QUERY_IMAGE_FORMATS:
        raise ValueError(
            'Unsupported image format; accepted: ' + ', '.join(sorted(QUERY_IMAGE_FORMATS))
        )
    if already_canonical and source_format == 'JPEG':
        data, steps = raw, ['trusted_image_reused_without_reencoding']
    else:
        try:
            data, _ = convert_to_jpeg(raw)
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError('The image could not be converted to the canonical JPEG') from exc
        steps = ['formatted_zone.format_images.convert_to_jpeg']
    _, config = load_policy()
    try:
        metrics, _ = analyze(data, config)
    except ValueError as exc:  # e.g. above the Trusted 40 MP analysis budget
        raise ValueError(f'The image could not be analysed: {exc}') from exc
    flags = list(metrics['flags'])
    # In Trusted a small image is rejected; a query only receives a warning.
    rejection = image_rejection(metrics, config)
    if rejection:
        flags.append(rejection)
    steps.append('trusted_zone.quality.image_quality.analyze')
    kept = (
        'width',
        'height',
        'brightness_mean',
        'sharpness_laplacian',
        'chroma_mean',
        'aspect_ratio',
    )
    return PreparedQuery(
        'images',
        data,
        _report(
            'images',
            raw,
            source_format.lower(),
            'jpeg_rgb_q95',
            flags,
            IMAGE_WARNINGS,
            {key: metrics[key] for key in kept},
            steps,
        ),
    )


def prepare_query_audio(raw: bytes) -> PreparedQuery:
    """Formatted FLAC PCM16 conversion plus Trusted audio measurements as warnings."""
    from trusted_zone.pipeline_common import QualityFailure, load_policy
    from trusted_zone.quality.audio_quality import audio_metrics
    from trusted_zone.validate_audio import validate_config

    if not isinstance(raw, bytes) or not raw:
        raise ValueError('Expected audio bytes')
    source_format = detect_source_format(raw, '')
    if source_format not in QUERY_AUDIO_FORMATS:
        raise ValueError(
            'Unsupported audio format for in-memory queries; accepted: '
            + ', '.join(sorted(QUERY_AUDIO_FORMATS))
        )
    try:
        data, _, _ = convert_audio(raw, '', decoder='soundfile')
    except (RuntimeError, OSError) as exc:  # libsndfile errors derive from RuntimeError
        raise ValueError('The audio could not be converted to canonical FLAC') from exc
    _, config, _ = load_policy('trusted_audio_quality.yaml', 'audio')
    validate_config(config)
    # The corpus minimum duration is a rejection; for a query it becomes a warning.
    tolerant = {**config, 'min_duration_seconds': 0.0}
    try:
        metrics = audio_metrics(data, tolerant)
    except QualityFailure as exc:
        raise ValueError('The audio could not be decoded for quality analysis') from exc
    flags = list(metrics['flags'])
    if metrics['duration_seconds'] < config['min_duration_seconds']:
        flags.insert(0, 'duration_below_minimum')
    kept = ('sample_rate_hz', 'channels', 'duration_seconds', 'rms_dbfs', 'peak_dbfs')
    return PreparedQuery(
        'audio',
        data,
        _report(
            'audio',
            raw,
            source_format,
            'flac_pcm16',
            flags,
            AUDIO_WARNINGS,
            {key: metrics[key] for key in kept},
            [
                'formatted_zone.format_audio.convert_audio',
                'trusted_zone.quality.audio_quality.audio_metrics',
            ],
        ),
    )
