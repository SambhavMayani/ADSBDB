# EcoSentinel

## Iberian Wildlife Multimodal Data Platform

EcoSentinel is a multimodal DataOps project focused on biodiversity monitoring and wildlife conservation in the Iberian Peninsula.

The goal of the project is to build an end-to-end data management pipeline capable of ingesting, processing, cleaning, organizing, and exploiting heterogeneous wildlife data.

---

## Data Modalities

The project considers three main data modalities:

- Images
- Audio
- Text

---

## Initial Data Sources

The initial data sources considered for the project are:

- **iNaturalist**: wildlife images and observation metadata.
- **Xeno-canto**: wildlife audio recordings.
- **MITECO**: official species information.
- **GBIF**: taxonomic information and normalization.

---

## Pilot Species

The initial pilot focuses on the following Iberian wildlife species:

- *Lynx pardinus* — Iberian lynx
- *Canis lupus* — Iberian wolf
- *Cervus elaphus* — Red deer
- *Sus scrofa* — Wild boar
- *Aquila chrysaetos* — Golden eagle
- *Bubo bubo* — Eurasian eagle-owl
- *Erithacus rubecula* — European robin
- *Alcedo atthis* — Common kingfisher
- *Pelophylax perezi* — Iberian water frog
- *Timon lepidus* — Ocellated lizard

The species configuration is centralized in:

```text
config/species.yaml
```

This avoids hardcoding the species list inside the ingestion scripts.

---

## Pipeline Architecture

EcoSentinel follows the zone-based DataOps architecture defined in the P1 project specification.

```text
Data Sources
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

### Landing Zone

The Landing Zone is the entry point of the system.

It is divided into:

- **Temporal Landing**: stores raw data as obtained from the original sources.
- **Persistent Landing**: stores the ingested data permanently after applying organization and naming conventions.

### Formatted Zone

The Formatted Zone will homogenize the representation of each data modality into canonical formats.

### Trusted Zone

The Trusted Zone will apply generic data quality and cleaning processes independently for images, audio, and text.

### Exploitation Zone

The Exploitation Zone will generate embeddings from the trusted data and store them in a vector database such as ChromaDB.

These embeddings will later support similarity search and multimodal retrieval tasks.

---

## Repository Structure

```text
ecosentinel-adsdb/
|
|-- config/
|   `-- species.yaml
|
|-- landing_zone/
|   |-- temporal_landing/
|   `-- persistent_landing/
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
|
|-- docker-compose.yml
|-- requirements.txt
|-- .env.example
|-- .gitignore
`-- README.md
```

The repository contains the code and configuration of the pipeline.

The actual multimodal data is not stored directly in Git. Landing, Formatted, and Trusted data are stored in an S3-compatible object storage service.

---

## Object Storage

The project uses an S3-compatible object storage service deployed using Docker.

The current Docker environment uses **SILO**, which is compatible with the MinIO/S3 API and allows the project to use `boto3` from Python.

The storage service exposes:

```text
S3 API:      http://localhost:9000
Web console: http://localhost:9001
```

The web interface is intended only for inspection.

Buckets, folders, and data should be created and managed programmatically by the project scripts.

---

# Local Setup

## 1. Clone the Repository

Clone the repository and enter the project directory.

```bash
git clone <repository-url>
cd <repository-folder>
```

---

## 2. Install Docker Desktop

Docker Desktop must be installed and running.

On Windows, the project has been tested using Docker Desktop with the WSL 2 backend.

Check that Docker is available:

```bash
docker --version
```

If Git Bash does not resolve the command correctly, use:

```bash
docker.exe --version
```

Check Docker Compose:

```bash
docker.exe compose version
```

---

## 3. Configure Environment Variables

The repository contains:

```text
.env.example
```

Create your own local `.env` file:

```bash
cp .env.example .env
```

Then edit it:

```bash
nano .env
```

Example configuration:

```env
MINIO_ROOT_USER=ecosentinel_admin
MINIO_ROOT_PASSWORD=your_local_password
```

Each developer should use their own local credentials.

The `.env` file is ignored by Git and must never be committed to the repository.

---

## 4. Start the Object Storage

Start the Docker environment:

```bash
docker.exe compose up -d
```

Check that the container is running:

```bash
docker.exe ps
```

The expected container name is:

```text
ecosentinel-minio
```

The web console can then be accessed at:

```text
http://localhost:9001
```

Log in using the credentials configured in your local `.env` file.

---

# Python Environment

## 5. Create a Virtual Environment

Create the Python virtual environment:

```bash
python -m venv .venv
```

Activate it from Git Bash on Windows:

```bash
source .venv/Scripts/activate
```

After activation, the terminal should display something similar to:

```text
(.venv)
```

---

## 6. Install Python Dependencies

Install the project dependencies:

```bash
python -m pip install -r requirements.txt
```

The current dependencies include:

- `boto3`
- `python-dotenv`

`boto3` is used to communicate with the S3-compatible object storage API.

`python-dotenv` is used to load local credentials and configuration from `.env`.

---

# Storage Initialization

## 7. Test the Storage Connection

With Docker running and the Python virtual environment activated, execute:

```bash
python orchestration/check_minio_connection.py
```

A successful connection should display:

```text
Connection to MinIO successful.
```

It will also list the currently available buckets.

---

## 8. Initialize the Storage Buckets

Run:

```bash
python orchestration/initialize_storage.py
```

The script programmatically creates the storage buckets required for the data management pipeline:

```text
landing-zone
formatted-zone
trusted-zone
```

The script checks whether each bucket already exists before attempting to create it.

Therefore, it can safely be executed multiple times.

---

# Storage Architecture

The current storage organization is:

```text
S3-Compatible Object Storage
|
|-- landing-zone
|
|-- formatted-zone
|
`-- trusted-zone
```

The Landing Zone will later contain two logical areas:

```text
landing-zone/
|
|-- temporal_landing/
|
`-- persistent_landing/
```

The Temporal Landing will receive raw data from the external sources.

The Persistent Landing will contain permanently stored data with standardized organization and naming conventions.

---

# Data Flow

The expected data flow is:

```text
External APIs / Data Sources
        |
        v
Temporal Landing
        |
        v
Persistent Landing
        |
        v
Formatted Zone
        |
        v
Trusted Zone
        |
        v
Embedding Generation
        |
        v
ChromaDB / Exploitation Zone
        |
        v
Multimodal Tasks
```

Each zone will consume data from the previous zone, apply its corresponding transformations, and store the resulting data in the next zone.

All movement between storage zones must be performed programmatically.

---

# Metadata and Traceability

Each asset will maintain only metadata that has a clear purpose in the pipeline.

Examples include:

```text
asset_id
scientific_name
modality
source_name
source_record_id
ingestion_timestamp
license
original_filename
```

Metadata will be used when necessary for:

- Traceability between zones.
- Data lineage.
- Incremental ingestion.
- Identification of the original source.
- Licensing information.
- Filtering and retrieval.
- Linking embeddings with the original assets.

Metadata fields should not be added unless they have a clear use in the project.

---

# Stopping the Environment

To stop the Docker services:

```bash
docker.exe compose down
```

The Docker volume is persistent, so stored objects are preserved when the container is stopped.

To start the environment again:

```bash
docker.exe compose up -d
```

---

# Current Project Status

Currently completed:

- Initial Git repository structure.
- Zone-based code organization.
- Temporal and Persistent Landing structure.
- Pilot species configuration.
- Docker-based S3-compatible object storage.
- Environment variable configuration.
- Python virtual environment setup.
- Python connection to the object storage using `boto3`.
- Programmatic bucket initialization.
- Landing, Formatted, and Trusted storage buckets.

---

# Next Development Step

The next step is to implement the **Landing Zone ingestion pipeline**.

This will include programmatic ingestion from the selected external data sources and storage of raw data in the Temporal Landing.

No data should be uploaded manually through the object storage web interface.
