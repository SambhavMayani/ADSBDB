# EcoSentinel — Decision Log

This file records the main architectural decisions already taken in the project. It is intended to prevent loss of context between team members and to provide material for the final report and presentation.

---

## D01 — Use MinIO as object storage

**Decision**

Use a MinIO-compatible S3 object store deployed with Docker for Landing, Formatted and Trusted data.

**Why**

- appropriate for unstructured multimodal data;
- programmatic S3-compatible access through `boto3`;
- supports object metadata;
- easy visual inspection through the UI;
- aligns with the project architecture.

**Trade-off**

Requires Docker infrastructure and explicit object-key conventions.

---

## D02 — Keep acquisition, Temporal and Persistent as separate scripts

**Decision**

Use separate responsibilities:

```text
data acquisition
→ ingest_local_data.py
→ process_to_persistent.py
```

**Why**

Each script has one clear responsibility and can evolve independently.

**Rejected alternative**

One large script performing download + upload + persistence.

**Reason rejected**

Harder to test, reuse and maintain across modalities.

---

## D03 — Preserve raw source files in Landing

**Decision**

Do not convert JPEG/PNG/WEBP, audio formats or text representations during Landing acquisition.

**Why**

Landing represents the raw reproducible source state.

**Where conversion belongs**

Formatted Zone.

---

## D04 — Use the local folder hierarchy as an explicit ingestion contract

**Decision**

Use:

```text
data/raw_dataset/<modality>/<species_id>/<file>
```

**Why**

- simple;
- readable;
- deterministic;
- sufficient for the project scale;
- accepted by the project supervisor.

**Trade-off**

The local ingestor is not fully independent from folder layout.

**Future production alternative**

Global manifest/catalog carrying modality and taxonomy independently from physical paths.

---

## D05 — Keep acquisition metadata beside the raw assets

**Decision**

Each species acquisition directory contains `_metadata.json`.

**Why**

Provides provenance close to the raw source assets and lets the common ingestor recover `source_name`.

**Required common fields**

```text
local_filename
source_name
species_id
```

---

## D06 — Reject unknown provenance

**Decision**

Do not ingest assets whose `source_name` is missing or `unknown`.

**Why**

Once raw assets move farther into the pipeline, missing provenance makes organization and traceability unreliable.

**Historical note**

Several Bubo bubo Temporal objects were created before the acquisition metadata was available. They were removed from Temporal and re-ingested after metadata was corrected.

---

## D07 — Use SHA-256 as a technical checksum, not as Trusted deduplication

**Decision**

Compute SHA-256 over raw file bytes.

**Why**

- deterministic content fingerprint;
- traceability;
- useful technical identity.

**Important distinction**

SHA-256 compares bytes, not visual or semantic similarity.

A recompressed or resized version of the same image can have a different SHA-256.

**Therefore**

Quality duplicate detection remains a Trusted Zone responsibility.

---

## D08 — Use `<hash16>__<filename>` in Temporal

**Decision**

Temporal key:

```text
temporal_landing/<first-16-SHA256>__<filename>
```

**Why**

The combination distinguishes technical ingestion assets while keeping keys readable.

**Behavior**

```text
same bytes + same filename
→ same Temporal identity

same bytes + different filename
→ different Temporal identity

same filename + different bytes
→ different Temporal identity
```

**Trade-off**

Only 16 hexadecimal hash characters are retained. Collision risk is negligible at the project scale but not theoretically zero.

---

## D09 — Keep data-quality duplicate handling out of Landing

**Decision**

Landing prevents accidental repeated ingestion of the same technical asset but does not decide whether two dataset assets are quality duplicates.

**Why**

Ingestion idempotence and data-quality deduplication are different responsibilities.

**Trusted will later handle**

- exact duplicate detection;
- possibly near-duplicate detection;
- semantic/content quality rules.

---

## D10 — Do not use Persistent scanning as the final incremental-ingestion mechanism

**Decision**

Do not make `ingest_local_data.py` list/search Persistent Landing for every asset.

**Alternative considered**

Search Persistent metadata or keys to determine whether an asset had already been processed.

**Why rejected as final design**

- couples ingestion to Persistent organization;
- requires searching/listing rather than a direct lookup;
- becomes less attractive as the repository grows;
- future changes to Persistent organization would affect the ingestor.

---

## D11 — Do not use a local JSON ingestion registry

**Decision**

Do not store the authoritative ingestion state only on a developer's machine.

**Why**

The project has multiple contributors. Local state could differ across computers, be deleted, or not match the shared MinIO environment.

---

## D12 — Use a MinIO completion registry

**Decision**

Store one deterministic marker per successfully completed Landing ingestion:

```text
_control/completed/<control_id>.json
```

**Control ID**

```text
SHA256(full Temporal key)
```

**Why**

- direct object lookup;
- shared team state;
- independent from Persistent layout;
- independent from future zones;
- simple failure recovery;
- easy to explain and inspect.

**Marker creation rule**

A marker is created only after the Persistent object has been verified.

---

## D13 — Use the full SHA-256 for control IDs

**Decision**

The control-marker filename contains a full 64-character hexadecimal SHA-256.

**Why**

It is an internal key where readability is less important than deterministic uniqueness.

**Difference from Temporal**

Temporal uses a shortened hash for readable object naming; `_control` uses the full SHA-256 of the complete Temporal key.

---

## D14 — Completion identity is based on the full Temporal key

**Decision**

Hash:

```text
temporal_landing/<hash16>__<filename>
```

to generate the control ID.

**Why**

This preserves filename identity in addition to byte identity.

**Result**

A byte-identical asset under a different filename can still enter Landing and later be evaluated by Trusted.

---

## D15 — Persistent organization is modality + species

**Decision**

Use:

```text
persistent_landing/<modality>/<species_id>/
```

**Why**

These are stable, high-value dimensions for EcoSentinel and simplify downstream discovery.

---

## D16 — Persistent filename contains source, species, timestamp and hash

**Decision**

Use:

```text
<source>$<species>$<timestamp>$<hash>.<extension>
```

**Why**

- source provenance is visible;
- species is explicit;
- ingestion time supports version/history reasoning;
- hash provides technical traceability;
- extension preserves the raw file type.

---

## D17 — Persistent timestamp is the original Temporal ingestion time

**Decision**

Use the Temporal object's `LastModified` as ingestion time rather than the later copy time.

**Why**

The timestamp should describe when the raw asset entered the Landing pipeline.

**Time zone**

UTC.

---

## D18 — Delete Temporal only after Persistent and control are verified

**Decision**

Processing order:

```text
copy Persistent
→ verify Persistent
→ create marker
→ verify marker
→ delete Temporal
```

**Why**

This prioritizes recoverability and avoids losing the transient raw copy before durable state has been confirmed.

---

## D19 — Add backfill for pre-registry Persistent objects

**Decision**

Support:

```bash
python landing_zone/persistent_landing/process_to_persistent.py --backfill-control
```

**Why**

One object had already reached Persistent before the completion registry was introduced.

**Why not fix it manually**

All MinIO changes should remain programmatic and reproducible.

---

## D20 — Use UTC for operational timestamps

**Decision**

Persist timestamps in UTC.

**Why**

Avoid ambiguity across machines, local time zones and daylight-saving transitions.

---

## D21 — Save acquisition metadata after every successful Wikimedia asset

**Decision**

Update `_metadata.json` incrementally.

**Why**

Avoid a situation where files have been downloaded but metadata is lost because the process stopped before completing the full species batch.

---

## D22 — Add HTTP retries and request delay for Wikimedia

**Decision**

Use retries for rate limits/temporary server errors and a small delay between API requests.

**Why**

External APIs are not perfectly reliable and acquisition should tolerate transient failures.

---

## D23 — Apply only technical filters during Wikimedia acquisition

**Decision**

Filter by:

- supported MIME type;
- minimum long-side resolution;
- maximum file size.

**Why**

These checks prevent obviously unsuitable technical assets without turning acquisition into the Trusted quality stage.

**Limitation**

Technical filtering does not guarantee semantic quality. Wikimedia categories can contain illustrations, historical media or otherwise less useful visual examples.

---

## D24 — Make local filenames Windows-safe

**Decision**

Replace characters invalid on Windows and truncate excessively long filenames while preserving their extension.

**Why**

A Wikimedia source title produced a local path that Windows could not create.

**Selected local maximum**

Approximately 140 filename characters, leaving margin for the project directory path.

---

## D25 — Do not preserve empty Temporal folders artificially

**Decision**

Allow `temporal_landing/` to disappear from the MinIO UI when empty.

**Why**

S3/MinIO folders are key prefixes, not real directories.

Adding a placeholder object would introduce artificial data that every script would then need to ignore.

---

## D26 — Common Landing scripts must support all project modalities

**Decision**

The same:

```text
ingest_local_data.py
process_to_persistent.py
```

will handle images, audio and text.

**Why**

At these stages the operations are generic: raw bytes + common metadata.

**Modality-specific behavior belongs to**

- acquisition scripts;
- Formatted scripts;
- Trusted quality scripts.

---

## D27 — Freeze common Landing after image validation

**Decision**

Do not independently modify the common Landing scripts while audio/text contributors are developing acquisition.

**Why**

Reduces merge conflicts and prevents modality-specific logic from leaking into generic scripts.

Any required change should first be identified as a genuinely common requirement.

---

## D28 — Documentation split

**Decision**

Use:

- code comments/docstrings for local implementation understanding;
- repository documentation for architecture and decisions;
- final report for concise justifications, pros/cons and limitations.

**Why**

This keeps scripts readable without duplicating the final explanatory report.

---


## D29 — Use JPEG as the canonical image encoding in Formatted

**Decision**

All formatted images use JPEG with the `.jpg` extension.

**Why**

- One predictable syntax for subsequent processing.
- Wide support across image-processing tools.
- Generally appropriate file sizes for the predominantly photographic wildlife dataset.

**Trade-off**

JPEG uses lossy compression and may alter image pixels. The raw source remains available in Persistent Landing.

---

## D30 — Encode formatted images as RGB

**Decision**

Convert all supported source pixel modes to RGB before JPEG encoding.

**Why**

A single compatible pixel mode reduces variation in downstream decoding.

**Trade-off**

Original source modes and transparency cannot be represented identically by RGB JPEG.

---

## D31 — Flatten transparency over white

**Decision**

Composite source images containing transparency onto an opaque white background.

**Why**

JPEG does not support alpha transparency.

**Trade-off**

The appearance of previously transparent pixels depends on the chosen background. Persistent retains the original image.

---

## D32 — Use JPEG quality 95

**Decision**

Use `quality=95` as a fixed encoder parameter.

**Why**

Provides a consistent conversion policy that prioritizes visual fidelity for photographic images.

**Trade-off**

This is **not** a quality score; even high-quality JPEG recompression remains lossy. File sizes may vary.

---

## D33 — Preserve dimensions and defer visual quality corrections

**Decision**

Formatted does not resize, crop, sharpen, deduplicate or rotate image pixels to correct EXIF orientation.

**Why**

Its responsibility is format homogenization rather than generic data cleaning or model-specific preparation.

**Trade-off**

Different source resolutions remain present. Some viewers may interpret retained EXIF orientation metadata differently.

---

## D34 — Convert only the primary MPO frame

**Decision**

Allow internal MPO encoding even when the source filename ends in `.jpg`; export frame 0 as the canonical JPEG.

**Why**

Maintains the intended one-source-object-to-one-formatted-object mapping and allows all wildlife image assets to pass the same formatted contract.

**Evidence**

Four eagle MPO source objects contained two frames each, and two wolf MPO source objects contained three frames each.

**Trade-off**

Eight non-primary internal frames are not exported. The six original complete MPO files remain stored in Persistent Landing.

**Alternative**

Export all frames into separate JPEGs with explicit frame identifiers and one-to-many lineage. This remains an option if analytical tasks need secondary frames.

---

## D35 — Mirror species hierarchy and retain original source identity

**Decision**

Use `formatted-zone/images/<species_id>/<persistent_filename_stem>.jpg` for outputs.

**Why**

The Persistent filename already includes source, species, UTC ingestion timestamp and raw technical hash.

**Important**

The embedded `asset_hash` describes the raw input asset. It is not the checksum of the converted JPEG.

---

## D36 — Propagate lineage and record the format policy

**Decision**

Copy relevant Persistent object metadata and add `source_persistent_key_encoded`, `original_format`, `formatted_format`, `color_mode`, `jpeg_quality`, `format_version` and `formatted_at`.

**Why**

Allows downstream systems to trace a canonical asset to its raw source and identify the transformation policy.

**Trade-off**

S3 user metadata is not a full metadata catalog. Richer future lineage may require structured sidecar documents or a separate registry.

---

## D37 — Keep Persistent Landing intact during formatting

**Decision**

Do not delete or replace raw Persistent objects after successfully creating canonical images.

**Why**

Supports auditability, reproduction, and reformatting if transformation policy changes or errors are found.

**Trade-off**

Maintaining raw and formatted copies consumes additional storage.

---

## D38 — Use deterministic output keys and conflict-safe reexecution

**Decision**

Skip a previously formatted asset only when its destination metadata and format policy match expectations. Report incompatible existing outputs as errors instead of overwriting them.

**Why**

Prevents duplicate work and avoids silently hiding changed formatting contracts or incorrect lineage.

**Trade-off**

A changed formatting policy requires explicit versioning and planned regeneration of existing objects.

---

## D39 — Keep formatting separate for each modality

**Decision**

Image conversion lives in `formatted_zone/format_images.py`. Audio and text will have their own dedicated scripts.

**Why**

The P1 specification requires per-format homogenization scripts, and the actual conversions are modality-specific.

**Status**

Image formatting completed and validated; audio and text formatting pending.

---

## D40 — Validate the entire image batch in Formatted

**Decision**

Check actual decoded JPEG encoding, RGB mode, `.jpg` extension, metadata lineage, per-species counts, and absence of processing errors.

**Evidence**

Final validation passed for all 100 images (10 per species) with zero errors. Persistent Landing still holds the 100 originals.

**Limitation**

This technical validation does not replace the qualitative profiling and cleaning required in Trusted.

---

## Current handoff state

**Implemented and validated for images**

- Wikimedia image acquisition and accompanying metadata.
- Common Temporal and Persistent Landing flow, completion registry, and incremental behavior.
- Formatted image conversion to JPEG/RGB, including first-frame MPO support.
- End-to-end verification: 100 raw Persistent image objects and 100 valid canonical Formatted images (10 per species, zero formatting/validation errors).

**Implemented in the shared repository; full validation not yet recorded here**

- Audio acquisition script: `landing_zone/data_acquisition/download_xeno_canto_audio.py`.
- Text acquisition script: `landing_zone/data_acquisition/download_species_texts.py`.
- Audio acquisition tests: `tests/test_audio_acquisition.py` (presence of tests does not imply the complete dataset has been validated).

**Pending**

- Full audio and text acquisition validation and any necessary integration changes.
- Modality-specific audio and text formatting.
- Trusted Zone, Exploitation Zone, multimodal tasks and final orchestration.
- Final report and presentation.

This status is a handoff snapshot, not a substitute for fresh test execution on each developer's environment.
