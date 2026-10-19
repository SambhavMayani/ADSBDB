"""Generate Trusted Audio/Text quality reports from MinIO per-object manifests.

Reports read ONLY _quality/<modality>/*.json, never original media again.
JSON, CSV, HTML and PNG files are local reproducible artifacts, ignored by Git.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape

from trusted_zone.pipeline_common import ROOT, TRUSTED_BUCKET, client_from_env, load_policy

TEMPLATES = Path(__file__).resolve().parent / "templates"
FEATURES = {
    "audio": [
        ("duration_seconds", "Recording duration", "Seconds", "duration.png"),
        ("rms_dbfs", "RMS sound level", "dBFS", "rms.png"),
        ("peak_dbfs", "Peak level", "dBFS", "peak.png"),
        ("clipping_sample_pct", "Potential clipping", "% of samples", "clipping.png"),
        ("low_energy_window_pct", "Low-energy windows", "% of 50-ms windows", "low_energy.png"),
        ("sample_rate_hz", "Sampling rate", "Hz", "sample_rate.png"),
    ],
    "text": [
        ("words", "Document length", "Words", "words.png"),
        ("characters", "Character count", "Characters", "characters.png"),
        ("unique_word_ratio", "Lexical variety (TTR)", "Distinct tokens / tokens", "lexical_variety.png"),
        ("alphanumeric_ratio", "Alphanumeric character ratio", "Fraction", "alphanumeric.png"),
        ("formatted_size_bytes", "Formatted document size", "Bytes", "size.png"),
    ],
}


def rows_from_minio(client, modality: str) -> list[dict]:
    rows = []
    prefix = f"_quality/{modality}/"
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=TRUSTED_BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            if not item["Key"].endswith(".json"):
                continue
            obj = client.get_object(Bucket=TRUSTED_BUCKET, Key=item["Key"])
            try:
                rows.append(json.loads(obj["Body"].read()))
            finally:
                obj["Body"].close()
    return sorted(rows, key=lambda row: row.get("source_key", ""))


def _number_summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    numbers = sorted(values)
    def percentile(p):
        index = (len(numbers) - 1) * p
        low, high = math.floor(index), math.ceil(index)
        return numbers[low] * (1 - (index - low)) + numbers[high] * (index - low)
    return {"count": len(values), "mean": round(mean(values), 4),
            "median": round(median(values), 4), "min": min(numbers), "max": max(numbers),
            "p10": round(percentile(0.1), 4), "p90": round(percentile(0.9), 4)}


def aggregate(rows: list[dict], modality: str):
    statuses = Counter(row.get("status", "unknown") for row in rows)
    before_species = Counter(row.get("species_id", "unknown") for row in rows)
    after_species = Counter(row.get("species_id", "unknown") for row in rows if row.get("status") == "accepted")
    before_sources = Counter(row.get("source_name", "unknown") for row in rows)
    after_sources = Counter(row.get("source_name", "unknown") for row in rows if row.get("status") == "accepted")
    reasons = Counter(row.get("reason") for row in rows if row.get("reason"))
    flags = Counter(flag for row in rows for flag in row.get("metrics", {}).get("flags", []))
    prov = sum(bool(row.get("source_name") not in {None, "", "unknown"} and row.get("source_etag")) for row in rows)
    measurements = {}
    for field, _, _, _ in FEATURES[modality]:
        values = [row.get("metrics", {}).get(field) for row in rows]
        measurements[field] = _number_summary([float(x) for x in values if isinstance(x, (float, int)) and not isinstance(x, bool)])
    if modality == "audio":
        source_bytes = sum(float(row.get("metrics", {}).get("file_size_mb") or 0) * 1_000_000 for row in rows)
        accepted_bytes = sum(float(row.get("metrics", {}).get("file_size_mb") or 0) * 1_000_000 for row in rows if row.get("status") == "accepted")
        extras = {
            "sample_rate_counts": dict(sorted(Counter(str(row.get("metrics", {}).get("sample_rate_hz", "unknown")) for row in rows).items())),
            "channel_counts": dict(sorted(Counter(str(row.get("metrics", {}).get("channels", "unknown")) for row in rows).items())),
        }
    else:
        source_bytes = sum(row.get("metrics", {}).get("formatted_size_bytes", 0) for row in rows)
        accepted_bytes = sum(row.get("metrics", {}).get("trusted_size_bytes", 0) for row in rows if row.get("status") == "accepted")
        extras = {
            "possible_emails_total": sum(row.get("metrics", {}).get("possible_emails_count", 0) for row in rows),
            "possible_ipv4_total": sum(row.get("metrics", {}).get("possible_ipv4_count", 0) for row in rows),
        }
    summary = {
        "modality": modality, "analyzed": len(rows), "accepted": statuses["accepted"],
        "rejected": statuses["rejected"], "errors": statuses["error"],
        "acceptance_rate_pct": round(100 * statuses["accepted"] / len(rows), 2) if rows else 0,
        "provenance_coverage_pct": round(100 * prov / len(rows), 2) if rows else 0,
        "source_measured_mb": round(source_bytes / 1_000_000, 4),
        "trusted_measured_mb": round(accepted_bytes / 1_000_000, 4),
        "species_before": dict(sorted(before_species.items())),
        "species_after": dict(sorted(after_species.items())),
        "sources_before": dict(sorted(before_sources.items())),
        "sources_after": dict(sorted(after_sources.items())),
        "reasons": dict(sorted(reasons.items())), "quality_flags": dict(sorted(flags.items())),
        "measurements": measurements, **extras,
    }
    table = []
    for row in rows:
        record = {name: row.get(name) for name in (
            "source_key", "species_id", "source_name", "status", "reason", "source_etag",
            "source_sha256", "policy_version", "processing_seconds")}
        record["duplicate_of"] = (row.get("duplicate") or {}).get("canonical_key")
        record.update(row.get("metrics", {}))
        record["flags"] = ";".join(row.get("metrics", {}).get("flags", []))
        record["near_duplicate_candidate"] = json.dumps(record.get("near_duplicate_candidate") or {}, ensure_ascii=False)
        table.append(record)
    return summary, table


def _save(fig, path: Path):
    fig.savefig(path, dpi=145, bbox_inches="tight")
    plt.close(fig)


def _before_after(before: dict, after: dict, title: str, path: Path):
    labels = sorted(set(before) | set(after))
    fig, ax = plt.subplots(figsize=(max(8, min(13, len(labels) * 0.85)), 4.5))
    x = range(len(labels))
    ax.bar([v - 0.2 for v in x], [before.get(k, 0) for k in labels], width=0.4, label="Formatted")
    ax.bar([v + 0.2 for v in x], [after.get(k, 0) for k in labels], width=0.4, label="Trusted")
    ax.set_xticks(list(x), labels, rotation=32, ha="right")
    ax.set_ylabel("Assets")
    ax.set_title(title)
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    _save(fig, path)


def _histogram(rows: list[dict], field: str, title: str, units: str, path: Path):
    before = [float(row["metrics"][field]) for row in rows
              if isinstance(row.get("metrics", {}).get(field), (int, float))]
    after = [float(row["metrics"][field]) for row in rows
             if row.get("status") == "accepted" and isinstance(row.get("metrics", {}).get(field), (int, float))]
    fig, ax = plt.subplots(figsize=(7.8, 3.7))
    if before:
        bins = min(18, max(4, round(math.sqrt(len(before)))))
        edges = np.histogram_bin_edges(before, bins=bins)
        ax.hist(before, bins=edges, alpha=0.65, label="Formatted: all evaluated")
        if after:
            ax.hist(after, bins=edges, histtype="step", linewidth=2, label="Trusted: accepted subset")
        ax.legend()
    ax.set_title(title)
    ax.set_xlabel(units)
    ax.set_ylabel("Assets")
    ax.grid(axis="y", alpha=0.2)
    _save(fig, path)


def generate(client, modality: str, version: str, config: dict, output: Path | None = None) -> Path:
    if modality not in FEATURES:
        raise ValueError("Expected audio or text modality")
    rows = rows_from_minio(client, modality)
    if not rows:
        raise ValueError(f"No Trusted {modality} quality manifests found")
    now = datetime.now(timezone.utc)
    base = output or ROOT / "reports" / "trusted_quality" / modality / now.strftime("%Y%m%dT%H%M%SZ")
    base.mkdir(parents=True, exist_ok=True)
    summary, table = aggregate(rows, modality)
    summary.update({
        "policy_version": version, "policy": config, "generated_at_utc": now.isoformat(),
        "report_scope": f"All _quality/{modality}/ manifests currently in MinIO",
        "caveat": "Charts compare evaluated Formatted assets against the accepted subset; they do not imply the accepted media were acoustically/textually modified. Manifest timestamps refer to each object's last changed evaluation; removed upstream objects may leave stale manifests.",
    })
    (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = list(dict.fromkeys(name for record in table for name in record))
    with (base / "metrics.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        writer.writerows(table)
    _before_after(summary["species_before"], summary["species_after"],
                  f"{modality.title()} by species", base / "species_before_after.png")
    _before_after(summary["sources_before"], summary["sources_after"],
                  f"{modality.title()} by data source", base / "sources_before_after.png")
    for field, title, units, filename in FEATURES[modality]:
        _histogram(rows, field, title, units, base / filename)
    template = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    output_html = base / "quality_report.html"
    output_html.write_text(template.get_template("audio_text.html.j2").render(
        summary=summary, date=now.strftime("%Y-%m-%d %H:%M UTC"),
        features=FEATURES[modality]), encoding="utf-8")
    return output_html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modality", choices=["audio", "text"])
    args = parser.parse_args()
    version, config, _ = load_policy(f"trusted_{args.modality}_quality.yaml", args.modality)
    print(generate(client_from_env(), args.modality, version, config))


if __name__ == "__main__":
    main()
