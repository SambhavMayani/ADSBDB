"""Build a reproducible HTML/CSV/JSON Trusted Images quality report.

The input consists exclusively of versioned per-asset quality manifests in
MinIO. It never re-opens the original images or recomputes their metrics.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from jinja2 import Environment, FileSystemLoader, select_autoescape

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
BUCKET = os.getenv("ECOSENTINEL_TRUSTED_BUCKET", "trusted-zone")
QUALITY_PREFIX = "_quality/images/"
TEMPLATES = Path(__file__).resolve().parent / "templates"


def iter_manifests(client):
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=QUALITY_PREFIX):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.endswith(".json"):
                continue
            response = client.get_object(Bucket=BUCKET, Key=key)
            try:
                yield json.loads(response["Body"].read())
            finally:
                response["Body"].close()


def _save_figure(fig, path: Path) -> None:
    fig.savefig(path, dpi=145, bbox_inches="tight")
    plt.close(fig)


def _bar_plot(labels: list[str], before: list[int], after: list[int], target: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5))
    positions = list(range(len(labels)))
    ax.bar([p - 0.2 for p in positions], before, width=0.4, label="Formatted (before)")
    ax.bar([p + 0.2 for p in positions], after, width=0.4, label="Trusted (after)")
    ax.set_xticks(positions, labels, rotation=33, ha="right")
    ax.set_ylabel("Images")
    ax.set_title("Images per species: before and after quality controls")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    _save_figure(fig, target)


def _histogram(values: list[float], name: str, units: str, target: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 3.7))
    if values:
        ax.hist(values, bins=min(18, max(3, int(len(values) ** 0.5))))
    ax.set_xlabel(units)
    ax.set_ylabel("Images")
    ax.set_title(name)
    ax.grid(axis="y", alpha=0.2)
    _save_figure(fig, target)


def _distribution_shift(before: Counter, after: Counter) -> float:
    """Jensen-Shannon divergence (bits) between before/after species shares."""
    keys = set(before) | set(after)
    total_before, total_after = sum(before.values()), sum(after.values())
    if not total_before or not total_after:
        return 0.0
    divergence = 0.0
    for key in keys:
        p = before[key] / total_before
        q = after[key] / total_after
        midpoint = (p + q) / 2
        if p:
            divergence += 0.5 * p * math.log2(p / midpoint)
        if q:
            divergence += 0.5 * q * math.log2(q / midpoint)
    return round(divergence, 6)


def aggregate(rows: list[dict]) -> tuple[dict, list[dict]]:
    statuses = Counter(row.get("status", "unknown") for row in rows)
    reasons = Counter(row.get("reason") for row in rows if row.get("reason"))
    flags = Counter(flag for row in rows for flag in row.get("metrics", {}).get("flags", []))
    watermarks = Counter(row.get("watermark", {}).get("status", "not_assessed") for row in rows)
    methods = Counter(row.get("watermark", {}).get("method", "not_assessed") for row in rows)
    species_in = Counter(row.get("species_id", "unknown") for row in rows)
    species_out = Counter(row.get("species_id", "unknown") for row in rows if row.get("status") == "accepted")
    sources_in = Counter(row.get("source_name", "unknown") for row in rows)
    sources_out = Counter(row.get("source_name", "unknown") for row in rows if row.get("status") == "accepted")
    reasons_by_species = Counter((row.get("species_id", "unknown"), row.get("reason")) for row in rows if row.get("reason"))
    source_mb = sum(float(row.get("metrics", {}).get("size_mb") or 0) for row in rows)
    accepted_mb = sum(float(row.get("metrics", {}).get("size_mb") or 0) for row in rows if row.get("status") == "accepted")
    measured_seconds = sum(float(row.get("processing_seconds") or 0) for row in rows)
    summary = {
        "images_analyzed": len(rows),
        "accepted": statuses["accepted"],
        "rejected": statuses["rejected"],
        "acceptance_rate_pct": round(100 * statuses["accepted"] / len(rows), 2) if rows else 0,
        "source_measured_mb": round(source_mb, 2),
        "trusted_measured_mb": round(accepted_mb, 2),
        "excluded_measured_mb": round(source_mb - accepted_mb, 2),
        "total_measured_processing_seconds": round(measured_seconds, 2),
        "measured_images_per_second": round(len(rows) / measured_seconds, 3) if measured_seconds else None,
        "reasons": dict(sorted(reasons.items())),
        "quality_flags": dict(sorted(flags.items())),
        "species_distribution_jsd_bits": _distribution_shift(species_in, species_out),
        "source_distribution_jsd_bits": _distribution_shift(sources_in, sources_out),
        "watermark_statuses": dict(sorted(watermarks.items())),
        "watermark_methods": dict(sorted(methods.items())),
        "species_before": dict(sorted(species_in.items())),
        "species_after": dict(sorted(species_out.items())),
        "sources_before": dict(sorted(sources_in.items())),
        "sources_after": dict(sorted(sources_out.items())),
        "species_retention_pct": {key: round(100 * species_out[key] / value, 2) for key, value in sorted(species_in.items())},
        "source_retention_pct": {key: round(100 * sources_out[key] / value, 2) for key, value in sorted(sources_in.items())},
        "provenance_completeness_pct": round(100 * sum(bool(row.get("source_name") and row.get("source_name") != "unknown" and row.get("source_etag")) for row in rows) / len(rows), 2) if rows else 0,
        "rejections_by_species": {f"{s}:{r}": c for (s, r), c in sorted(reasons_by_species.items())},
    }
    columns = [
        "source_key", "species_id", "source_name", "status", "reason", "policy_version", "processing_seconds",
        "width", "height", "megapixels", "size_mb", "aspect_ratio", "brightness_mean", "sharpness_laplacian", "chroma_mean",
        "phash", "flags", "watermark_method", "watermark_status", "duplicate_of",
    ]
    table = []
    for row in rows:
        m = row.get("metrics", {})
        record = {k: row.get(k, "") for k in columns}
        for key in ("width", "height", "megapixels", "size_mb", "aspect_ratio", "brightness_mean", "sharpness_laplacian", "chroma_mean", "phash"):
            record[key] = m.get(key, "")
        record["flags"] = ";".join(m.get("flags", []))
        record["watermark_method"] = row.get("watermark", {}).get("method", "")
        record["watermark_status"] = row.get("watermark", {}).get("status", "")
        record["duplicate_of"] = (row.get("duplicate") or {}).get("canonical_key", "")
        table.append(record)
    return summary, table


def generate(client, version: str, config: dict, output: Path | None = None) -> Path:
    """Write self-contained report artifacts to the repository's reports folder."""
    now = datetime.now(timezone.utc)
    base = output or Path(os.getenv("ECOSENTINEL_REPORT_ROOT", str(ROOT / "reports"))) / "trusted_quality" / "images" / now.strftime("%Y%m%dT%H%M%S_%fZ")
    base.mkdir(parents=True, exist_ok=True)
    rows = sorted(iter_manifests(client), key=lambda r: r.get("source_key", ""))
    # A partial earlier run must not silently produce a misleading global report.
    if not rows:
        raise ValueError("No Trusted image quality manifests found")
    summary, table = aggregate(rows)
    summary.update({
        "generated_at_utc": now.isoformat(),
        "policy_version": version,
        "policy": config,
        "report_scope": "All Trusted image quality manifests currently present in MinIO",
        "caveat": "Times are per-asset measurements from the latest evaluation, not an end-to-end batch benchmark.",
    })
    (base / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    with (base / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)

    labels = sorted(summary["species_before"])
    _bar_plot(labels, [summary["species_before"][s] for s in labels],
              [summary["species_after"].get(s, 0) for s in labels], base / "species_before_after.png")
    source_labels = sorted(summary["sources_before"])
    _bar_plot(source_labels, [summary["sources_before"][s] for s in source_labels],
              [summary["sources_after"].get(s, 0) for s in source_labels], base / "sources_before_after.png")
    charts = [
        ("megapixels", "Resolution distribution", "Megapixels", "resolution.png"),
        ("size_mb", "File size distribution", "MB", "file_size.png"),
        ("brightness_mean", "Brightness distribution", "Mean intensity (0-255)", "brightness.png"),
        ("aspect_ratio", "Aspect ratio distribution", "Width / height", "aspect_ratio.png"),
        ("sharpness_laplacian", "Sharpness distribution", "Laplacian variance (proxy)", "sharpness.png"),
    ]
    for column, name, units, filename in charts:
        values = [float(record[column]) for record in table if record[column] != ""]
        _histogram(values, name, units, base / filename)

    renderer = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    html = renderer.get_template("images.html.j2").render(summary=summary, rows=table, date=now.strftime("%Y-%m-%d %H:%M UTC"))
    (base / "quality_report.html").write_text(html, encoding="utf-8")
    LOGGER.info("Wrote %s", base / "quality_report.html")
    return base / "quality_report.html"


def main():
    import sys
    sys.path.insert(0, str(ROOT / "trusted_zone"))
    from trusted_zone.validate_images import load_policy, s3_client
    version, config = load_policy()
    print(generate(s3_client(), version, config))


if __name__ == "__main__":
    main()
