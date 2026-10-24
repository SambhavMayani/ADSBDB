"""Pure image-quality operations shared by Trusted ingestion and tests.

All measurement thresholds live in config/trusted_quality.yaml. Dark, blurry,
monochrome, panoramic, and watermark-suspected images are not discarded.
"""

from __future__ import annotations

import io
import os
import shutil
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps
from skimage.metrics import structural_similarity


@dataclass
class ImageFeatures:
    """Compact fingerprints used for non-quadratic candidate lookup."""

    phash: int
    grey: np.ndarray
    color: np.ndarray


def _phash(grey: np.ndarray) -> int:
    """Compute a standard 64-bit perceptual DCT hash (8x8 low frequencies)."""
    small = cv2.resize(grey, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(small.astype(np.float32))[:8, :8]
    values = dct.flatten()
    median = float(np.median(values[1:]))  # DC excluded from threshold
    bits = values > median
    result = 0
    for bit in bits:
        result = (result << 1) | int(bit)
    return result


def analyze(data: bytes, config: dict) -> tuple[dict, ImageFeatures]:
    """Fully decode a bounded JPEG and return metrics plus duplicate features."""
    # Decode in isolation: an OSError here describes input bytes, whereas an
    # OSError from S3 must remain an operational failure in the caller.
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'JPEG':
                raise ValueError(f'Expected JPEG, received {image.format}')
            width, height = image.size
            if width * height > config['max_megapixels'] * 1_000_000:
                raise ValueError('resolution_limit_exceeded')
            # Orientation metadata changes perceived pixels; use it for analysis only.
            rgb = ImageOps.exif_transpose(image).convert('RGB')
            pixels = np.asarray(rgb)
    except OSError as exc:
        raise ValueError(f'invalid_image_payload:{type(exc).__name__}') from exc

    if pixels.size == 0:
        raise ValueError('empty_pixels')
    preview = cv2.resize(pixels, (256, 256), interpolation=cv2.INTER_AREA)
    grey = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(preview, cv2.COLOR_RGB2LAB)
    luminance = float(grey.mean())
    sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
    chroma = float(
        np.mean(
            np.abs(lab[:, :, 1].astype(np.float32) - 128)
            + np.abs(lab[:, :, 2].astype(np.float32) - 128)
        )
    )
    ratio = width / height
    flags = []
    if luminance < config['dark_mean_threshold']:
        flags.append('low_brightness')
    if sharpness < config['blur_laplacian_threshold']:
        flags.append('low_sharpness')
    if chroma < config['monochrome_chroma_threshold']:
        flags.append('monochrome_like')
    if not (config['aspect_ratio_warning_min'] <= ratio <= config['aspect_ratio_warning_max']):
        flags.append('unusual_aspect_ratio')

    metrics = {
        'width': width,
        'height': height,
        'megapixels': round(width * height / 1_000_000, 4),
        'aspect_ratio': round(ratio, 4),
        'size_mb': round(len(data) / 1_000_000, 4),
        'brightness_mean': round(luminance, 3),
        'sharpness_laplacian': round(sharpness, 3),
        'chroma_mean': round(chroma, 3),
        'phash': f'{_phash(grey):016x}',
        'flags': flags,
    }
    return metrics, ImageFeatures(int(metrics['phash'], 16), grey, preview)


def phash_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()


def confirm_duplicate(
    first: ImageFeatures, second: ImageFeatures, config: dict
) -> tuple[bool, float, float]:
    """Confirm appearance equivalence; high precision beats aggressive recall."""
    ssim = float(structural_similarity(first.grey, second.grey, data_range=255))
    color_dist = float(
        np.mean(np.abs(first.color.astype(np.float32) - second.color.astype(np.float32))) / 255.0
    )
    return (
        ssim >= config['duplicate_ssim_min']
        and color_dist <= config['duplicate_color_distance_max'],
        round(ssim, 5),
        round(color_dist, 5),
    )


def image_rejection(metrics: dict, config: dict) -> str | None:
    if metrics['width'] < config['min_width'] or metrics['height'] < config['min_height']:
        return 'dimensions_too_small'
    return None


def assess_watermark(pixels: np.ndarray, method: str, config: dict) -> dict:
    """Tag possible overlays; do not claim to certify copyright or watermark absence.

    Advanced mode uses local Tesseract OCR. Its detections are still ambiguous:
    text in the scene, date stamps, or logos can resemble watermarks. Lightweight
    mode only detects overlays with simple edge/text-like patterns.
    """
    if method == 'advanced':
        try:
            import pytesseract

            custom_binary = os.getenv('TESSERACT_CMD')
            if custom_binary:
                pytesseract.pytesseract.tesseract_cmd = custom_binary
            result = pytesseract.image_to_data(
                Image.fromarray(pixels),
                output_type=pytesseract.Output.DICT,
                config='--psm 11',
                timeout=10,
            )
            matches = []
            for token, confidence in zip(result['text'], result['conf']):
                try:
                    strength = float(confidence)
                except (ValueError, TypeError):
                    continue
                if strength >= 60 and len(token.strip()) >= 3:
                    matches.append(token.strip()[:50])
            return {
                'method': 'advanced_ocr',
                'status': 'possible' if matches else 'no_indicator',
                'signals': len(matches),
            }
        except (ImportError, RuntimeError, OSError):
            # Missing OCR binary or runtime error must be visible in the report.
            method = 'lightweight_fallback'

    grey = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    height, width = grey.shape
    # Edges near image corners often correspond to overlays or date stamps.
    edges = cv2.Canny(grey, 90, 180)
    corner = max(8, min(height, width) // 5)
    rois = [
        edges[:corner, :corner],
        edges[:corner, -corner:],
        edges[-corner:, :corner],
        edges[-corner:, -corner:],
    ]
    strength = max(float(np.mean(region > 0)) for region in rois)
    return {
        'method': method,
        'status': 'possible'
        if strength >= config['watermark_lightweight_signal_threshold']
        else 'no_indicator',
        'signal_strength': round(strength, 4),
    }


def has_tesseract() -> bool:
    """OCR is optional and never downloaded implicitly."""
    configured = os.getenv('TESSERACT_CMD')
    if configured:
        return os.path.isfile(configured)
    return shutil.which('tesseract') is not None
