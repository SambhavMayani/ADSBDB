# EcoSentinel

**Iberian wildlife retrieval and evidence-based question answering.** ADSDB P1, UPC.

Authors: **Mario Rodrigo, Sambhav Mayani and Wassim Ouadie**.

EcoSentinel turns images, field recordings and species descriptions into a traceable corpus. It implements four data zones, same-modality search (Task 1), cross-modality search (Task 2), and retrieval-augmented generation (Task 3), with a local web interface.

**Start here:** [user guide](docs/user_guide.md) · [project report](docs/ecosentinel_report.pdf) · [validation](docs/testing_and_validation.md) · [technical documentation](docs/README.md).

## How to use this repository

To understand the project, read the architecture below, then the [project report](docs/ecosentinel_report.pdf). The [documentation index](docs/README.md) links to the implementation details in pipeline order; those references are not prerequisites for running the application.

For a first run, follow this sequence:

1. **Install and verify** using the commands below.
2. **Prepare storage and models** under [first-run setup](#first-run-setup).
3. **Choose one data route:** acquire new wildlife data (A), process supplied raw files (B), or use an [already prepared installation](#run-the-existing-corpus) (C).
4. **Run the pipeline** for A/B and wait for `Pipeline status: completed`. Route C verifies existing outputs instead.
5. **Create or reuse the query copy and start the web** at **http://127.0.0.1:8765**.
6. **Try Tasks 1, 2 and 3** using the [interface cases](docs/user_guide.md#cases-to-try-in-the-interface), then inspect the sources and quality reports.

A code-only clone can run the offline tests. The full application also needs local object storage, cached model weights and either supplied raw data with metadata or provider access for acquisition. Reproducing the exact reference results requires the authors' matching dataset and metadata. New downloads can produce different results.

### Submission ZIP: supplied raw dataset

The submission ZIP includes `data/raw_dataset/` alongside this README and the source code. These are the original inputs: **100 images, 34 recordings and 64 texts**, organised by modality and species. Each species folder includes `_metadata.json` with filenames, source information, available attribution/licences and checksums. The empty lizard audio metadata records that no recording was available for that species.

Extract the complete ZIP and run commands from the folder containing this README. Keep the dataset in `data/raw_dataset/` and retain all metadata files. Complete **Install and verify** and **First-run setup** below, then follow **route B** to process these supplied files. Do not use `--with-acquisition` for the supplied dataset; no provider API key is needed for this route. Model preparation still requires Internet to download pretrained weights on the first run.

The raw dataset is supplied with the assessment ZIP and remains excluded from GitHub. Model weights, prebuilt indexes, storage volumes, runtime reports and local credentials are not included; the setup and pipeline create the required local state. Asset-specific attribution and licence information remain in the metadata.

## Architecture

```text
Optional acquisition → Security Gate → Temporal / Persistent Landing
    → Formatted (JPEG / FLAC PCM16 / UTF-8 text)
    → Trusted (quality, provenance, deduplication and reports)
    → Exploitation (five persistent Chroma collections)
    → Task 1 / Task 2 / Task 3 → local web interface
```

The reference corpus has **198 accepted assets**: 100 images, 34 recordings and 64 texts. Its five collections contain **6,021 embeddings**. Counts describe the audited local corpus, not a fresh download. Data, model weights, `.env`, indexes and runtime reports are excluded from Git. A fresh clone can run offline tests without any of them.

## Install and verify

Use **64-bit Python 3.11**. Commands are for **Git Bash on Windows**, from the repository root. Docker Desktop is needed only for object storage and integration tests.

**GitHub clone:** obtain the code with:

```bash
git clone https://github.com/SambhavMayani/ADSBDB.git
cd ADSBDB
```

**Submission ZIP:** extract the complete archive and open Git Bash inside its `EcoSentinel/` folder, which contains this README and `data/raw_dataset/`. Skip the clone commands above and work in this supplied copy.

From either starting point, install and verify:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m orchestration.pipeline --plan
```

On Linux, activate with `source .venv/bin/activate` and install `torch==2.14.1` from `https://download.pytorch.org/whl/cpu` before the same requirements. No CUDA, paid model API or Tesseract installation is required for the baseline. Dependency installation requires Internet; default tests do not download models or access production MinIO.

### Optional: isolated storage integration test

This verifies storage contracts using generated fixtures. It does not prepare the wildlife dataset or the application. Skip to first-run setup to start the application.

```bash
# Isolated integration: separate port, test credentials, no production volume.
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:19000/minio/health/ready
python -m pytest -m integration -q
docker compose -p ecosentinel-tests -f docker-compose.test.yml down
```

## First-run setup

After installation, keep the virtual environment active and start Docker Desktop. For a new installation, create `.env` and set its local storage credentials before starting the service:

```bash
cp -n .env.example .env
# Edit .env: set MINIO_ROOT_USER and MINIO_ROOT_PASSWORD.
docker compose up -d
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:9000/minio/health/ready
python orchestration/check_minio_connection.py
python -m exploitation_zone.prepare_models --download
python -m exploitation_zone.prepare_models
```

Expected: `Connection to object storage successful` and `Embedding models ready`. Keep existing credentials when using a prepared installation. Model preparation downloads pretrained weights once; `pip` installs the code that uses them. The pipeline loads cached weights and does not download them automatically.

**To run all three Tasks**, also complete the [Qwen and BLIP preparation commands](docs/user_guide.md#2-prepare-models-explicitly). These two models are needed for Task 3; the embedding models above cover Tasks 1 and 2. No training is required.

### A. No local raw data

Configure the [acquisition prerequisites](docs/user_guide.md#a-no-local-raw-files-acquire-and-process-wildlife), including `XENO_CANTO_API_KEY` in `.env`. With Internet access, storage running and the models ready:

```bash
python -m orchestration.pipeline --plan --with-acquisition
python -m orchestration.pipeline --run --with-acquisition
```

This selects 19 steps: image, audio and text acquisition, then all zones and reconciliation. Provider availability and quotas can cause failures or different counts; inspect the run report. The flag acquires wildlife data, not model weights. After `Pipeline status: completed`, continue to [start the interface](#start-the-interface-after-route-a-or-b).

### B. Raw files already local

Retain the supplied files and `_metadata.json` sidecars under `data/raw_dataset/<modality>/<species_id>/` (the submission ZIP already includes this raw dataset). A code-only clone does not contain them. Complete the first-run setup above, then run the 16-step route without acquisition. This generates the embeddings and builds the local vector index from the supplied originals; precomputed embeddings are not included in the ZIP:

```bash
python -m orchestration.pipeline --plan
python -m orchestration.pipeline --run
```

### Start the interface after route A or B

After `Pipeline status: completed`, with index writers stopped:

```bash
python -m orchestration.reconcile
python -m orchestration.audit --source data/chromadb --snapshot data/search_index
python -m multimodal_tasks.search --status
python -m webapp.server
```

The pipeline builds/verifies the zones and original index; it does not start the web server or create its query snapshot. The snapshot command copies and verifies the existing vector database from `data/chromadb/` to `data/search_index/`. It does not recompute embeddings or copy source media. The web reads the snapshot and loads source media from object storage. Open **http://127.0.0.1:8765**.

Chroma stores the original index on disk between runs. The separate copy protects the audited index from Chroma's internal writes and costs extra database disk space. See the [user guide](docs/user_guide.md#4-start-the-reference-interface) for copy reuse, refresh, completion criteria and report locations.

This block assumes `data/search_index/` does not yet exist. Existing snapshots are never overwritten or refreshed automatically; use the next section for an already prepared installation. After corpus changes, create a snapshot at a new path and start the server with `--index NEW_PATH`.

## Run the existing corpus

Configure `.env` locally from `.env.example`, then start storage. Do not replace an existing `.env` or remove Docker volumes. The pinned S3-compatible container is SILO; Python uses the MinIO/S3 API.

```bash
cp -n .env.example .env
# Set local credentials before starting a new storage service.
docker compose up -d
python -m orchestration.reconcile
python -m orchestration.audit --source data/chromadb
# Once, with index writers stopped; omit if the snapshot already exists.
python -m orchestration.audit --source data/chromadb --snapshot data/search_index
python -m webapp.server
```

Open **http://127.0.0.1:8765**. Queries use a separate snapshot, `data/search_index/`; the original index is protected. External query files reuse Formatted conversions and Trusted quality measurements in memory. Quality warnings allow retrieval; shared resource limits reject unsafe inputs before conversion. Model preparation, fresh-clone setup and UI examples are in the [user guide](docs/user_guide.md).

Tasks 1 and 2 request up to **8 distinct assets** by default. Set **Cantidad (top-k)** in the web or use `--limit N` in the CLI for **1–50** results in total. **Modalidad de resultados** filters type independently. Task 3 uses its own evidence budget. See the [top-k explanation and examples](docs/user_guide.md#number-of-search-results-top-k-and---limit).

## Pipeline and recovery

```bash
python -m orchestration.pipeline --plan
python -m orchestration.pipeline --run
# After fixing a failure, resume at the required stage:
python -m orchestration.pipeline --run --from-stage exploitation
```

`--run` writes missing outputs; it is unnecessary for an already reconciled corpus. Acquisition is added only with `--with-acquisition`. Compatible embeddings are reused. Logs and atomic JSON reports explain failures; reconciliation checks hashes and segment coverage. See [orchestration](docs/pipeline_orchestration.md).

## Quality and scope

GitHub Actions defines Windows/Linux offline checks, static analysis, formatting, a coverage floor and isolated Linux S3 integration. Local results and remote workflow results are reported separately. [Validation](docs/testing_and_validation.md) records outcomes and limits; [documentation](docs/README.md) explains each zone and Task.

Similarity is not a species probability. RAG validates quoted evidence but does not prove biological truth or conclusively identify an external photograph. This CPU-oriented prototype is intended for local use. [Data and model provenance](docs/data_sources.md) records sources and reuse considerations.
