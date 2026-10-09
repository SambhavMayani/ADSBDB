# EcoSentinel

## Iberian Wildlife Multimodal Data Platform

EcoSentinel is a multimodal DataOps project focused on biodiversity monitoring and wildlife conservation in the Iberian Peninsula.

The goal is to build an end-to-end data management pipeline capable of ingesting, organizing, formatting, cleaning and exploiting heterogeneous wildlife data while preserving provenance and traceability.

The project currently works with three modalities:

- Images
- Audio
- Text

---

# 1. Project Context

Wildlife information is commonly distributed across different providers, formats and modalities. EcoSentinel centralizes this information in a zone-based data architecture so that it can later support:

- structured data management;
- multimodal exploration;
- same-modality similarity search;
- cross-modal retrieval;
- embedding-based search;
- generative multimodal tasks.

The initial pilot contains ten Iberian wildlife species:

| Species ID | Scientific name |
|---|---|
| `lynx_pardinus` | *Lynx pardinus* |
| `canis_lupus` | *Canis lupus* |
| `cervus_elaphus` | *Cervus elaphus* |
| `sus_scrofa` | *Sus scrofa* |
| `aquila_chrysaetos` | *Aquila chrysaetos* |
| `bubo_bubo` | *Bubo bubo* |
| `erithacus_rubecula` | *Erithacus rubecula* |
| `alcedo_atthis` | *Alcedo atthis* |
| `pelophylax_perezi` | *Pelophylax perezi* |
| `timon_lepidus` | *Timon lepidus* |

The species configuration is centralized in:

```text
config/species.yaml
```

This prevents the species list from being hardcoded inside ingestion scripts.

---

# 2. Data Sources

The current and planned sources are:

| Modality | Source | Status |
|---|---|---|
| Images | Wikimedia Commons | Implemented |
| Audio | Xeno-canto | Pending |
| Text | MITECO / other reliable biodiversity sources | Pending |

The image acquisition pipeline currently contains:

- 10 species;
- 10 images per species;
- 100 raw images in total;
- acquisition metadata for every downloaded image.

Raw data is not committed to Git.

---

# 3. Pipeline Architecture

EcoSentinel follows a zone-based DataOps architecture:

```text
External Data Sources
        |
        v
Local Raw Dataset
        |
        v
Landing Zone
  |
  +-- Temporal Landing
  |
  +-- Persistent Landing
        |
        v
Formatted Zone
        |
        v
Trusted Zone
        |
        v
Exploitation Zone
        |
        v
Multimodal Tasks
```

## Landing Zone

The Landing Zone is the entry point of the system.

It is divided into:

- **Temporal Landing**: transient raw storage. Assets remain here until they are safely processed.
- **Persistent Landing**: permanent raw storage with organization, naming conventions and traceability metadata.

The image flow is currently implemented and validated end-to-end.

## Formatted Zone

The Formatted Zone will convert each modality into a canonical representation while preserving the original raw asset in Landing.

## Trusted Zone

The Trusted Zone will perform modality-specific quality checks and cleaning.

This is also where true dataset duplicate detection belongs.

## Exploitation Zone

The Exploitation Zone will generate embeddings from Trusted data and store them in modality-specific vector collections, planned with ChromaDB.

---

# 4. Repository Structure

```text
ecosentinel-adsdb/
|
|-- config/
|   `-- species.yaml
|
|-- landing_zone/
|   |
|   |-- data_acquisition/
|   |   `-- download_wikimedia_images.py
|   |
|   |-- temporal_landing/
|   |   `-- ingest_local_data.py
|   |
|   `-- persistent_landing/
|       `-- process_to_persistent.py
|
|-- formatted_zone/
|
|-- trusted_zone/
|
|-- exploitation_zone/
|
|-- multimodal_tasks/
|
|-- orchestration/
|   |-- check_minio_connection.py
|   `-- initialize_storage.py
|
|-- tests/
|
|-- docs/
|   |-- landing_zone_documentation.md
|   `-- decision_log.md
|
|-- docker-compose.yml
|-- requirements.txt
|-- .env.example
|-- .gitignore
`-- README.md
```

The repository stores code, configuration and documentation.

The actual multimodal assets are stored locally during acquisition and in object storage during pipeline execution.

---

# 5. Local Raw Data Contract

All acquisition scripts must write data using the following structure:

```text
data/raw_dataset/
├── images/
│   └── <species_id>/
│       ├── <asset files>
│       └── _metadata.json
├── audio/
│   └── <species_id>/
│       ├── <asset files>
│       └── _metadata.json
└── text/
    └── <species_id>/
        ├── <asset files>
        └── _metadata.json
```

This structure is the common contract used by the Landing ingestion scripts.

Each `_metadata.json` record must contain at least:

```text
local_filename
source_name
species_id
```

The ingestion script derives `modality` and `species_id` from the directory hierarchy and reads `source_name` from acquisition metadata.

`source_name="unknown"` is rejected.

Audio and text contributors should respect this contract and should not modify the common Landing scripts unless a genuinely shared requirement is identified.

---

# 6. Object Storage

The project uses an S3-compatible object storage service deployed with Docker.

The current Docker environment uses **SILO**, which is compatible with the MinIO/S3 API and can be accessed from Python through `boto3`.

Service endpoints:

```text
S3 API:      http://localhost:9000
Web console: http://localhost:9001
```

The web interface is only used for inspection and debugging.

All bucket creation, uploads, copies and deletions are performed programmatically.

Current buckets:

```text
landing-zone
formatted-zone
trusted-zone
```

The Landing bucket contains three logical areas:

```text
landing-zone/
├── temporal_landing/
├── persistent_landing/
└── _control/
    └── completed/
```

`temporal_landing/` may disappear from the MinIO UI when empty. This is expected because S3-style folders are logical key prefixes rather than physical directories.

---

# 7. Landing Zone Design

## Temporal Landing

Local assets are uploaded with keys following:

```text
temporal_landing/<hash16>__<filename>
```

Example:

```text
temporal_landing/07c5c9dbf9959468__wild_boar.jpg
```

`hash16` is derived from the first 16 hexadecimal characters of the file SHA-256.

The combination of content hash and filename is deliberate:

```text
same bytes + same filename
→ same technical ingestion identity

same bytes + different filename
→ different ingestion asset

same filename + different bytes
→ different ingestion asset
```

Landing therefore handles ingestion identity, not semantic duplicate detection.

## Persistent Landing

Persistent objects are organized as:

```text
persistent_landing/<modality>/<species_id>/<filename>
```

Persistent filenames follow:

```text
<source>$<species>$<timestamp>$<hash>.<extension>
```

Example:

```text
persistent_landing/images/sus_scrofa/
wikimedia_commons$sus_scrofa$05-10-2026_15-29-36$07c5c9dbf9959468.jpg
```

The timestamp corresponds to the original Temporal ingestion time and is expressed in UTC.

---

# 8. Incremental Ingestion

Incremental ingestion is implemented using a completion registry stored in MinIO:

```text
_control/completed/
```

For every asset that successfully completes Landing, the pipeline creates:

```text
_control/completed/<control_id>.json
```

where:

```text
control_id = SHA256(full Temporal object key)
```

The full 64-character SHA-256 is intentionally retained for control markers.

The registry allows `ingest_local_data.py` to determine whether an asset has already completed Landing without scanning Persistent storage.

The ingestion decision is:

```text
Build Temporal key
      |
      v
Already exists in Temporal?
  Yes -> SKIP TEMPORAL
  No
      |
      v
Completion marker exists?
  Yes -> SKIP COMPLETED
  No
      |
      v
Upload to Temporal
```

This makes repeated ingestion runs safe and idempotent.

---

# 9. Safe Temporal to Persistent Processing

`process_to_persistent.py` follows this order:

```text
1. Validate Temporal metadata
2. Build Persistent key
3. Copy object to Persistent
4. Verify Persistent object
5. Create completion marker
6. Verify completion marker
7. Delete Temporal object
```

Temporal deletion happens last.

This minimizes the risk of losing an asset if an intermediate operation fails.

A backfill command is available for Persistent objects created before the completion registry existed:

```bash
python landing_zone/persistent_landing/process_to_persistent.py --backfill-control
```

---

# 10. Why `_control/completed/` Exists

Several alternatives were considered for incremental ingestion:

- allow repeated Persistent versions and clean them later in Trusted;
- scan Persistent on every ingestion;
- keep a local JSON registry;
- keep state in SQLite;
- store deterministic completion markers in MinIO.

The completion registry was selected because it provides:

- direct object lookup;
- shared state between team members;
- no dependency on Persistent naming/layout;
- no dependency on Formatted or Trusted;
- clear recovery semantics;
- simple inspection and debugging.

The trade-off is that `_control` introduces extra operational state that must remain synchronized with Persistent storage.

To mitigate this, markers are only created after the Persistent object has been verified.

More detail is available in:

```text
docs/decision_log.md
docs/landing_zone_documentation.md
```

---

# 11. Image Acquisition

The current implemented acquisition script is:

```text
landing_zone/data_acquisition/download_wikimedia_images.py
```

It:

- loads species from `config/species.yaml`;
- queries Wikimedia Commons;
- downloads JPEG, PNG and WEBP assets;
- applies technical size/resolution filters;
- captures provenance and licensing metadata;
- computes SHA-256;
- writes `_metadata.json`;
- supports incremental execution;
- retries temporary HTTP/API failures;
- writes metadata after every successful asset;
- sanitizes Windows-invalid filename characters;
- truncates excessively long filenames while preserving the extension.

The acquisition layer does not convert image formats. Format normalization belongs to the Formatted Zone.

---

# 12. Local Setup

## 12.1 Clone the repository

```bash
git clone <repository-url>
cd <repository-folder>
```

## 12.2 Install Docker Desktop

Docker Desktop must be installed and running.

The project has been tested on Windows using Docker Desktop with the WSL 2 backend.

Check Docker:

```bash
docker --version
```

From Git Bash, if necessary:

```bash
docker.exe --version
```

Check Docker Compose:

```bash
docker.exe compose version
```

## 12.3 Configure environment variables

Create a local `.env` from:

```text
.env.example
```

From Git Bash:

```bash
cp .env.example .env
```

Example:

```env
MINIO_ROOT_USER=ecosentinel_admin
MINIO_ROOT_PASSWORD=your_local_password
```

Each developer should use local credentials.

`.env` is ignored by Git and must not be committed.

## 12.4 Start object storage

```bash
docker.exe compose up -d
```

Check the running container:

```bash
docker.exe ps
```

Expected container:

```text
ecosentinel-minio
```

Open the web console:

```text
http://localhost:9001
```

---

# 13. Python Environment

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it from Git Bash on Windows:

```bash
source .venv/Scripts/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

---

# 14. Initialize Storage

Test the object-storage connection:

```bash
python orchestration/check_minio_connection.py
```

Initialize required buckets:

```bash
python orchestration/initialize_storage.py
```

The initialization script is idempotent and can safely be executed multiple times.

---

# 15. Running the Current Image Pipeline

## 15.1 Download images

Download up to 10 images per configured species:

```bash
python landing_zone/data_acquisition/download_wikimedia_images.py --limit 10
```

Run one species only:

```bash
python landing_zone/data_acquisition/download_wikimedia_images.py \
  --species timon_lepidus \
  --limit 10
```

Repeated execution is safe. Existing registered assets are reused rather than downloaded again.

## 15.2 Ingest local assets into Temporal

```bash
python landing_zone/temporal_landing/ingest_local_data.py
```

The script reports separate counters for uploaded assets, objects already in Temporal, already completed assets and errors.

## 15.3 Process Temporal into Persistent

Process all available Temporal assets:

```bash
python landing_zone/persistent_landing/process_to_persistent.py
```

Process only one asset:

```bash
python landing_zone/persistent_landing/process_to_persistent.py --max-items 1
```

Run without modifying storage:

```bash
python landing_zone/persistent_landing/process_to_persistent.py --dry-run
```

Backfill historical completion markers:

```bash
python landing_zone/persistent_landing/process_to_persistent.py --backfill-control
```

After a successful complete image run, the expected conceptual state is:

```text
Temporal image objects:       0
Persistent image objects:   100
Image completion markers:   100
```

---

# 16. Metadata and Traceability

Metadata is kept only when it has a clear purpose.

Examples include:

```text
scientific_name
modality
species_id
source_name
source_record_id
ingestion_timestamp
license
original_filename
asset_hash
```

Metadata supports:

- provenance;
- traceability between zones;
- incremental ingestion;
- source identification;
- licensing;
- filtering;
- downstream retrieval;
- linking embeddings to source assets.

---

# 17. Deduplication Responsibility

The Landing Zone does **not** perform quality deduplication.

Landing asks:

```text
Has this exact technical ingestion already completed Landing?
```

Trusted will later ask:

```text
Are these assets duplicates or near-duplicates from a data-quality perspective?
```

For example, the same bytes under a different filename may enter Landing as two ingestion assets and later be identified as an exact duplicate in Trusted.

This separation keeps ingestion control and quality control independent.

---

# 18. Documentation

Detailed Landing documentation:

```text
docs/landing_zone_documentation.md
```

Architectural decisions and their justification:

```text
docs/decision_log.md
```

These documents contain the rationale behind the completion registry, rejected alternatives, naming decisions, SHA-256 decisions, UTC timestamp decisions, the local-folder contract, limitations and trade-offs, and team handoff rules.

---

# 19. Team Development Rules

To reduce integration problems:

1. acquisition scripts may be developed independently by modality;
2. all acquisition scripts must respect the common local raw-data contract;
3. `ingest_local_data.py` and `process_to_persistent.py` are shared generic Landing components;
4. modality-specific logic should not be added to those shared scripts unless required by all modalities;
5. major architectural decisions should be recorded in `docs/decision_log.md`;
6. data should never be moved manually through the MinIO/SILO web UI.

---

# 20. Stopping the Environment

Stop Docker services:

```bash
docker.exe compose down
```

Stored objects remain available because the storage volume is persistent.

Start again:

```bash
docker.exe compose up -d
```

---

# 21. Current Project Status

| Component | Status |
|---|---|
| Repository structure | Complete |
| Species configuration | Complete |
| Docker/S3 infrastructure | Complete |
| Programmatic bucket initialization | Complete |
| Wikimedia image acquisition | Complete |
| Image metadata generation | Complete |
| Common raw-data contract | Complete |
| Temporal Landing ingestion | Complete |
| Persistent Landing processing | Complete |
| Completion registry | Complete |
| Incremental Landing ingestion | Complete |
| Image Landing end-to-end validation | Complete |
| Audio acquisition | Pending |
| Text acquisition | Pending |
| Formatted Zone | Pending |
| Trusted Zone | Pending |
| Exploitation Zone | Pending |
| Multimodal tasks | Pending |
| Final orchestration | Pending |

---

# 22. Next Development Step

The common Landing architecture and image modality are currently frozen unless a real integration issue is found.

The next parallel development tasks are:

```text
Audio acquisition
Text acquisition
```

Both should produce data compatible with:

```text
data/raw_dataset/<modality>/<species_id>/
```

so that the existing generic Landing scripts can process them without modification.

After acquisition for all modalities is complete, development continues with the Formatted and Trusted zones.
