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

## Current handoff state

### Completed

```text
Image acquisition
Image acquisition metadata
Temporal Landing
Persistent Landing
Completion registry
Incremental Landing behavior
Image end-to-end validation
```

### Next

```text
Audio acquisition
Text acquisition
Formatted Zone
Trusted Zone
Exploitation Zone
Multimodal tasks
Orchestration
Final report + README integration
```
