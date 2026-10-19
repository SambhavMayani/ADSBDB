# Trusted Images and Pre-Ingestion Security — Design Record

**Implementation:** first iteration of EcoSentinel's Trusted Zone. The audio and text
quality stages will be independent scripts and are not implemented by this package.

## Responsibilities

1. **Security Gate (before Temporal Landing):** allowlisted extensions per modality,
   file signatures, prevention of obvious executable masquerading, conservative
   resource limits, incident logging and nonzero error status. It is not an antivirus
   or a guarantee that accepted content is harmless.
2. **Trusted Images (after Formatted):** generic image integrity, cost/size bounds,
   deterministic near-duplicate control, objective metrics, lineage and audit records.
   Unlike model-specific preprocessing, Trusted does not crop, resize, brighten,
   sharpen, downsample or rewrite accepted JPEG payloads.
3. **Quality reporting:** generated HTML, plots, JSON and CSV based on the actual
   MinIO quality manifests, including before/after distributions and provenance.

## Explicit thresholds

| Check | Policy | Decision | Rationale |
|---|---:|---|---|
| Trusted JPEG bytes | 20 MB | Reject above | Conservative operational bound; Google Cloud Vision also limits submitted images to 20 MB, which is **not** a universal image-quality standard. |
| Trusted pixels | 40 MP | Reject above | Local compute/storage policy below Pillow's default warning threshold, not a scientific claim of poor quality. |
| Trusted dimensions | 128 px in each axis | Reject below | Small asset / thumbnail policy; smaller photographs can still have scientific value in other applications. |
| Extreme aspect ratio | < 0.2 or > 5.0 | Informational | Panoramas are retained. |
| Low brightness / sharpness / monochrome | Configured metric thresholds | Informational | Avoid ecological bias against night imagery, camera traps and action shots. |
| Pre-Landing image bytes | 200 MB | Block | High security guardrail, intentionally distinct from Trusted's 20 MB limit. |
| Pre-Landing image pixels | 80 MP | Block | Guard against disproportionate in-memory decoding; keep Pillow's own protections active. |
| Pre-Landing audio bytes | 1 GB | Block | Conservative safety cap, not an audio quality filter. |
| Pre-Landing text bytes | 250 MB | Block | Conservative safety cap, not a text quality filter. |
| Watermark OCR | <= 1000 images/batch, when Tesseract available | Adaptive | Example initial workload switch; expensive detection for small batches, cheap screening for big ones. |

The values above are versioned in `config/trusted_quality.yaml` and
`config/security_policy.yaml`. External evidence supports the **trade-offs**;
the particular limits are explicit EcoSentinel policy choices.

Sources:
- OWASP File Upload Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- Pillow security / decompression bombs: https://pillow.readthedocs.io/en/stable/handbook/security.html
- Google Cloud Vision supported images: https://docs.cloud.google.com/vision/docs/supported-files
- P1 course specification: Constraints 5 and 6, data quality and qualitative analysis.

## Duplicate handling

- Exact SHA-256 duplicates are removed from Trusted, while retained upstream.
- Perceptual hash provides candidate retrieval via SQLite and eight 8-bit bands.
- Strict SSIM **and** RGB-distance confirmation determines near duplicates.
- The canonical copy is the first admissible source in a deterministic key order;
  a future extension could rank by source reliability or sharpness before selecting.
- Same-image, conflicting-species labels are not silently merged: the later
  object is excluded with a `cross_species_duplicate` incident in its manifest.
- The SQLite candidate index lives in a temporary directory; no O(N²) brute-force
  comparisons or N-image arrays are held in application memory.
- A strict similarity threshold deliberately prioritizes avoiding false-positive
  deletion, so some altered crops, overlays and transformed versions can remain.

## Watermarks

Watermark handling is **not an exclusion filter** in v1. We tag `possible`,
`no_indicator`, or `not_assessed`, with the method. "No indicator" never proves
absence. OCR is powered by `pytesseract` and requires the Tesseract executable;
without it we run lightweight corner-edge screening and record the fallback.
The heuristic may flag text, timestamps or contrast-rich vegetation. Its
performance is not represented as validated classifier accuracy. No image
is manually queued for review by default.

## Data governance and idempotency

`trusted-zone/images/<species>/<filename>.jpg` stores only accepted images.
`trusted-zone/_quality/images/<species>/<filename>.json` stores a JSON record
for **every evaluated** image, including rejections and duplicate references.
The quality report is generated into `reports/trusted_quality/<UTC-run-id>/`.
Per-object writes are skipped when provenance hash and policy version match;
a previous Trusted copy is removed if it no longer passes checks. Images are
read from Formatted; upstream objects are never deleted.

Idempotency of outputs does not yet mean constant-time reruns: each invocation
re-evaluates the selected batch to detect changes and new duplicates. For
truly high-frequency million-object production, persistent fingerprint caches,
versioned incremental indexing and worker isolation would be the next step.

## Why not ACCEPTED / REVIEW / REJECTED?

A manual REVIEW queue can grow without bound on large ingestion batches.
Version 1 uses only deterministic **accepted/rejected** publication states,
with nonblocking quality flags and complete per-object explanations.

## Security demonstration

Create an **inert** test file with an `MZ` header named `.jpg`. Run the
Security Gate on it and demonstrate a `BLOCK` result and JSONL incident.
Never run suspicious files. File signature checks are defense-in-depth and
cannot prove that arbitrary media is safe; keep libraries updated and use
restricted environments for untrusted decoders. Production-grade isolation,
malware scanning and IAM hardening are distinct future enhancements.

## Quality report and analysis

The HTML report includes distributions of file size, resolution, aspect ratio,
luminance, sharpness; before-and-after image counts per species; reason counts,
watermark coverage, source/species retention, Jensen–Shannon distribution shift,
rough processed-file size changes, and per-file throughput.
Inspect changes per species and source to detect possible over-cleaning and
sampling bias. `metrics.csv` keeps the detailed provenance and flags; summary
aggregations come from the exact same records.

Do not claim the pipeline measured recall/precision of watermark detection or
that reduced duplicates always improves downstream retrieval: those are separate
experiments that require annotated reference data and image-search metrics.
