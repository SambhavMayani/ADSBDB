"""Conservative Unicode validation, profiling and text-similarity warnings."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from trusted_zone.pipeline_common import QualityFailure

TOKEN = re.compile(r"\b\w+\b", re.UNICODE)
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
HTML_TAG = re.compile(r"</?[A-Za-z][^>]{0,120}>")
MOJIBAKE = re.compile(r"(?:Ã[\x80-\xff]|Â[\x80-\xff]|â€|�)")


def normalize_text(data: bytes, config: dict) -> tuple[bytes, dict, frozenset[str]]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise QualityFailure("invalid_utf8") from exc
    if CTRL.search(text):
        raise QualityFailure("invalid_control_character")
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = normalized.lstrip("\ufeff")
    # Formatted already writes exactly one trailing LF; enforce that contract.
    normalized = normalized.rstrip("\n") + "\n"
    if not normalized.strip():
        raise QualityFailure("empty_text")
    tokens = TOKEN.findall(normalized)
    words = [token.casefold() for token in tokens]
    flags = []
    if len(words) < config["short_document_warning_words"]:
        flags.append("short_document")
    alpha_num = sum(char.isalnum() for char in normalized)
    visible = sum(not char.isspace() for char in normalized)
    ratio = alpha_num / visible if visible else 0.0
    if ratio < config["alphanumeric_ratio_warning"]:
        flags.append("low_alphanumeric_ratio")
    if HTML_TAG.search(normalized):
        flags.append("possible_html_artifacts")
    if MOJIBAKE.search(normalized):
        flags.append("possible_mojibake")
    emails = len(EMAIL.findall(normalized))
    ips = len(IPV4.findall(normalized))
    if emails:
        flags.append("possible_email_pii")
    if ips:
        flags.append("possible_ipv4_pii")
    if len(normalized.encode("utf-8")) != len(data):
        flags.append("unicode_or_line_ending_normalized")
    n = int(config["near_duplicate_shingle_words"])
    shingles = frozenset(" ".join(words[i:i+n]) for i in range(max(0, len(words) - n + 1)))
    metrics = {
        "formatted_size_bytes": len(data),
        "trusted_size_bytes": len(normalized.encode("utf-8")),
        "words": len(words),
        "characters": len(normalized),
        "lines": len(normalized.splitlines()),
        "unique_word_ratio": round(len(set(words)) / len(words), 4) if words else 0.0,
        "alphanumeric_ratio": round(ratio, 4),
        "possible_emails_count": emails,
        "possible_ipv4_count": ips,
        "normalized_content_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "flags": flags,
    }
    return normalized.encode("utf-8"), metrics, shingles


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def candidate_near_duplicate(shingles: frozenset[str], accepted: list, key: str, species: str, config: dict):
    if len(shingles) < config["near_duplicate_min_shingles"]:
        return None
    threshold = config["near_duplicate_jaccard_warning"]
    best = None
    for other in accepted:
        if len(other["shingles"]) < config["near_duplicate_min_shingles"]:
            continue
        score = jaccard(shingles, other["shingles"])
        if score >= threshold and (best is None or score > best["jaccard"]):
            best = {"canonical_key": other["key"], "jaccard": round(score, 4),
                    "cross_species": other["species"] != species, "decision": "review_only"}
    return best
