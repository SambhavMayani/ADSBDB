"""Pre-ingestion checks for local EcoSentinel assets.

This module does not execute uploads or user-supplied files. A rejection means
"unsafe or unsupported to process", not that malicious intent was proved.
The small bounded header inspection is deliberately independent from the
Trusted Zone's stricter, model-agnostic data-quality rules.

OWASP File Upload Cheat Sheet:
https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.request
import warnings
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image, UnidentifiedImageError

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "security_policy.yaml"
REPORT_FILE = ROOT / "reports" / "security" / "incidents.jsonl"

EXTENSIONS = {
    "images": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".mpo"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".mp4", ".aac", ".wma", ".aiff", ".aif", ".webm", ".mka", ".amr", ".caf", ".ac3"},
    "text": {".txt", ".text", ".md", ".markdown", ".html", ".htm", ".xhtml", ".xml", ".json", ".jsonl", ".ndjson", ".pdf", ".docx", ".odt"},
}
BINARY_DANGER = (
    (b"MZ", "windows_executable"),
    (b"\x7fELF", "elf_executable"),
    (b"\xcf\xfa\xed\xfe", "mach_o_executable"),
    (b"\xfe\xed\xfa\xcf", "mach_o_executable"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole_binary"),
)


@dataclass(frozen=True)
class SecurityVerdict:
    allowed: bool
    reason: str
    observed_type: str = "unknown"


def read_config(path: Path = DEFAULT_CONFIG) -> dict:
    """Load versioned safety limits and fail if the configuration is invalid."""
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    required = ("max_filename_length", "max_image_mb", "max_image_megapixels", "max_audio_mb", "max_text_mb")
    if not isinstance(config, dict) or any(not isinstance(config.get(k), int) or config[k] < 1 for k in required):
        raise ValueError(f"Invalid security policy: {path}")
    return config


def _magic_matches(header: bytes, extension: str, modality: str) -> bool:
    if modality == "images":
        if extension in {".jpg", ".jpeg", ".mpo"}:
            return header.startswith(b"\xff\xd8\xff")
        if extension == ".png":
            return header.startswith(b"\x89PNG\r\n\x1a\n")
        if extension == ".webp":
            return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        if extension == ".bmp":
            return header.startswith(b"BM")
        if extension == ".gif":
            return header.startswith((b"GIF87a", b"GIF89a"))
        if extension in {".tif", ".tiff"}:
            return header.startswith((b"II*\x00", b"MM\x00*"))
    if modality == "audio":
        checks = {
            ".flac": header.startswith(b"fLaC"),
            ".wav": header.startswith(b"RIFF") and header[8:12] == b"WAVE",
            ".ogg": header.startswith(b"OggS"),
            ".opus": header.startswith(b"OggS"),
            ".mp3": header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xff and header[1] & 0xe0 == 0xe0),
            ".m4a": header[4:8] == b"ftyp",
            ".mp4": header[4:8] == b"ftyp",
            ".aac": len(header) >= 2 and header[0] == 0xff and header[1] & 0xf0 == 0xf0,
            ".wma": header.startswith(bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")),
            ".aiff": header.startswith(b"FORM") and header[8:12] in {b"AIFF", b"AIFC"},
            ".aif": header.startswith(b"FORM") and header[8:12] in {b"AIFF", b"AIFC"},
            ".webm": header.startswith(b"\x1a\x45\xdf\xa3"),
            ".mka": header.startswith(b"\x1a\x45\xdf\xa3"),
            ".amr": header.startswith(b"#!AMR"),
            ".caf": header.startswith(b"caff"),
            ".ac3": header.startswith(b"\x0b\x77"),
        }
        return checks.get(extension, False)
    if modality == "text":
        if extension == ".pdf":
            return header.startswith(b"%PDF-")
        if extension in {".docx", ".odt"}:
            return header.startswith(b"PK\x03\x04")
        # Text content is intentionally decoded later by its dedicated format parser.
        # A binary executable or archive masquerading as text is always forbidden.
        if header.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")):
            return True  # Explicit Unicode BOM; decoding remains the formatter's job.
        return b"\x00" not in header and not header.startswith((b"PK\x03\x04", b"\x1f\x8b"))
    return False


def inspect_file(path: Path, modality: str, policy: dict) -> SecurityVerdict:
    """Inspect an untrusted local file without executing or converting it."""
    extension = path.suffix.lower()
    if modality not in EXTENSIONS or extension not in EXTENSIONS[modality]:
        return SecurityVerdict(False, "extension_not_allowed")
    if len(path.name) > policy["max_filename_length"] or any(c in path.name for c in ("\x00", ":", "\\")):
        return SecurityVerdict(False, "unsafe_filename")
    if path.is_symlink() or not path.is_file():
        return SecurityVerdict(False, "non_regular_file")
    size = path.stat().st_size
    if size == 0:
        return SecurityVerdict(False, "empty_file")
    max_mb = policy[f"max_{'image' if modality == 'images' else modality}_mb"]
    if size > max_mb * 1_000_000:
        return SecurityVerdict(False, "safety_size_limit_exceeded")
    with path.open("rb") as stream:
        header = stream.read(4096)
    for signature, label in BINARY_DANGER:
        if header.startswith(signature):
            return SecurityVerdict(False, "executable_or_active_binary_detected", label)
    if not _magic_matches(header, extension, modality):
        return SecurityVerdict(False, "file_signature_mismatch")
    if modality == "text" and extension in {".docx", ".odt"}:
        # Bound ZIP central-directory processing without extracting any content.
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > policy.get("max_archive_entries", 10_000):
                    return SecurityVerdict(False, "archive_entry_limit_exceeded")
                total = sum(item.file_size for item in entries)
                compressed = max(1, sum(item.compress_size for item in entries))
                if total > policy.get("max_archive_uncompressed_mb", 1000) * 1_000_000:
                    return SecurityVerdict(False, "archive_uncompressed_limit_exceeded")
                if total / compressed > policy.get("max_archive_ratio", 200):
                    return SecurityVerdict(False, "archive_compression_ratio_exceeded")
        except (OSError, ValueError, zipfile.BadZipFile):
            return SecurityVerdict(False, "invalid_archive")
    if modality == "images":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    width, height = image.size
                    if width * height > policy["max_image_megapixels"] * 1_000_000:
                        return SecurityVerdict(False, "safety_pixel_limit_exceeded", image.format or "image")
                    image.verify()  # Header/structure; full decoding occurs in Formatted.
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            return SecurityVerdict(False, "image_header_invalid")
    return SecurityVerdict(True, "allowed", modality)


def record_incident(path: Path, modality: str, verdict: SecurityVerdict, destination: Path = REPORT_FILE) -> None:
    """Append a minimal JSONL audit record; no file contents are retained."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        relative_path = str(path.resolve().relative_to(ROOT))
    except ValueError:
        relative_path = path.name
    event = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "relative_path": relative_path,
        "modality": modality,
        "reason": verdict.reason,
        "observed_type": verdict.observed_type,
        "event": "ingestion_blocked",
    }
    with destination.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    LOGGER.warning("SECURITY BLOCK: %s (%s)", path, verdict.reason)
    webhook = os.getenv("SECURITY_ALERT_WEBHOOK_URL", "").strip()
    if webhook:
        if not webhook.startswith("https://"):
            LOGGER.error("Security webhook disabled: HTTPS is required")
            return
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=5):
                pass
        except (OSError, ValueError) as exc:
            LOGGER.error("Security webhook delivery failed: %s", type(exc).__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, help="Check one file; omitting checks the full raw dataset")
    parser.add_argument("--modality", choices=sorted(EXTENSIONS))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    policy = read_config()
    root = ROOT / "data" / "raw_dataset"
    if args.path:
        if not args.modality:
            parser.error("--modality is required with --path")
        candidates = [(args.path, args.modality)]
    else:
        candidates = [(p, m) for m in sorted(EXTENSIONS) for p in sorted((root / m).glob("*/*")) if p.is_file() and p.name != "_metadata.json"]
    blocked = 0
    for path, modality in candidates:
        verdict = inspect_file(path, modality, policy)
        print(f"{'PASS' if verdict.allowed else 'BLOCK'} {modality}: {path.name} - {verdict.reason}")
        if not verdict.allowed:
            record_incident(path, modality, verdict)
            blocked += 1
    print(f"Security Gate: checked={len(candidates)} blocked={blocked}")
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
