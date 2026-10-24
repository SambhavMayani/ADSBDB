# EcoSentinel

**Iberian wildlife retrieval and evidence-based question answering.** ADSDB P1, UPC.

Authors: **Mario Rodrigo, Sambhav and Wassim**.

EcoSentinel turns images, field recordings and species descriptions into a traceable corpus. It implements four data zones, same-modality search (Task 1), cross-modality search (Task 2), and retrieval-augmented generation (Task 3), with a local web interface.

**Start here:** [user and assessor guide](docs/user_guide.md) · [project report](docs/ecosentinel_report.pdf) · [requirements](docs/p1_requirements.md) · [validation](docs/testing_and_validation.md).

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

```bash
git clone https://github.com/SambhavMayani/ADSBDB.git
cd ADSBDB
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m orchestration.pipeline --plan
```

There is **one requirements file**. On Linux, activate with `source .venv/bin/activate` and install `torch==2.14.1` from `https://download.pytorch.org/whl/cpu` before the same requirements. No CUDA, paid model API or Tesseract installation is required for the baseline. Dependency installation requires Internet; default tests do not download models or access production MinIO.

```bash
# Isolated integration: separate port, test credentials, no production volume.
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:19000/minio/health/ready
python -m pytest -m integration -q
docker compose -p ecosentinel-tests -f docker-compose.test.yml down
```

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

Open **http://127.0.0.1:8765**. Queries use a separate snapshot, `data/search_index/`; the original index is protected. External query files stay in memory. Model preparation, fresh-clone setup and UI examples are in the [user guide](docs/user_guide.md).

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
