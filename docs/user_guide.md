# EcoSentinel user and assessor guide

Run these commands in **Git Bash**, at the repository root, with `.venv` activated. The [README](../README.md) covers installation. This guide distinguishes a fresh clone from the authors' reference installation.

## 1. Verify code without data or models

```bash
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m orchestration.pipeline --plan
```

Expected: no dependency or lint errors, passing offline tests and a 16-step plan. Tests use generated files, temporary Chroma and controlled model doubles. They do not measure pretrained-model accuracy. The plan does not connect to storage or load models.

```bash
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:19000/minio/health/ready
python -m pytest -m integration -q
```

Expected: the integration test runs all zones twice using real S3 and Chroma with deterministic encoders, checks reconciliation and zero additional encoder calls. It creates and removes only its own test buckets on port 19000.

## 2. Prepare models explicitly

Dependency installation, model downloads and wildlife acquisition are separate operations. Prepare weights once while online:

```bash
python -m exploitation_zone.prepare_models --download
python -m exploitation_zone.prepare_models
python -m multimodal_tasks.rag_model --download
python -m multimodal_tasks.rag_model
# BLIP preparation without requiring a corpus or executing a query:
python -c "from huggingface_hub import snapshot_download; from multimodal_tasks.generate import MODEL, REVISION; snapshot_download(repo_id=MODEL, revision=REVISION, token=False)"
```

The first pair prepares/verifies CLIP, multilingual CLIP, CLAP and E5. The second pair prepares/verifies the pinned Qwen 3B Q4_K_M GGUF. Ordinary queries use the local cache. Keep several GiB free for embedding models. Qwen checks for at least **2.5 GiB available RAM** before loading. CPU requests can take minutes; the 120-second generation deadline excludes retrieval and model loading.

## 3. Fresh clone without the reference data

The repository excludes the authors' MinIO volume and 6,021-vector index. Two routes are available.

**Technical demonstration.** With the test service running and embedding weights cached:

```bash
python -m orchestration.smoke --run --workdir data/assessor-smoke
python -m orchestration.smoke --run --workdir data/assessor-smoke
```

Use a new folder for the first run, then intentionally reuse it. Expected: three synthetic assets, seven embeddings, reconciliation success; zero new vectors on repetition. This exercises real subprocesses, decoders, S3, Chroma and CPU models. The image is noise and the audio is a tone: this proves execution, **not wildlife relevance**. Reports are in that folder's `reports/` directory. If the ephemeral test service is recreated, choose a new smoke directory.

**Wildlife demonstration.** Use the reference data handed over by the authors, or acquire another sample:

```bash
cp -n .env.example .env
# Edit local storage credentials. Xeno-canto acquisition also requires its API key.
docker compose up -d
python -m orchestration.pipeline --plan --with-acquisition
python -m orchestration.pipeline --run --with-acquisition
```

This writes the zones and indexes the new corpus. APIs and available records change: a fresh acquisition does not promise 198 assets or 6,021 vectors. To use existing raw files, retain `_metadata.json` provenance sidecars under `data/raw_dataset/<modality>/<species_id>/` and omit `--with-acquisition`. Exact offline reproduction requires the original data handoff and cached weights; Git alone is insufficient. See [data sources](data_sources.md).

## 4. Start the reference interface

On the existing installation, first run read-only checks:

```bash
docker compose up -d
python -m orchestration.reconcile
python -m orchestration.audit --source data/chromadb
```

Expected collection counts: images 100, audio 357, text 547, image-text 1,763, audio-text 3,254; total 6,021. With index writers stopped, create a snapshot only if it does not exist:

```bash
python -m orchestration.audit --source data/chromadb --snapshot data/search_index
python -m multimodal_tasks.search --status
python -m webapp.server
```

Open **http://127.0.0.1:8765**. The snapshot command refuses to overwrite an existing folder. To refresh, choose a new path and start `python -m webapp.server --index NEW_PATH`. After code updates, stop the old backend with Ctrl+C, restart it and refresh with Ctrl+F5.

## 5. Exercise the Tasks in the interface

The UI is in Spanish. Generated wording and relevance can vary; inspect behavior, sources and trace instead of expecting an exact sentence.

| Case | UI action | Expected behavior |
|---|---|---|
| Task 1 text | **Explorar por texto**, text mode; `Hábitat del lince ibérico` | Text results with provenance |
| Task 1 image | **Buscar similares**, animal image, same modality | Image results; upload is not saved |
| Task 1 audio | Short wildlife recording, same modality | Audio results; maximum 30 seconds |
| Task 2 image-text | Image-text mode; `Iberian lynx in a forest` | Both images and texts if available |
| Task 2 audio-text | Audio-text mode; `owl calling at night` | Both recordings and texts; prefer English for CLAP |
| Task 2 federation | All modalities; `birds near a river` | Available image, audio and text rankings combined by RRF |
| Task 3 text | **Preguntar al corpus · RAG**; `¿Cuál es el hábitat del lince ibérico?` | Cited answer or explicit abstention |
| Task 3 image | Stored or uploaded animal image; `¿Qué animal es?` | Corpus candidate marked as a hypothesis, not confirmed identity |
| Task 3 two aspects | Image plus the question below | Separate supported claims, or explicit partial answer |
| Unsupported content | Ask for a species' complete genome | Abstention when the evidence is absent |
| Outside domain | RAG: `How do I bake a pizza?` | Domain abstention; heuristic can make mistakes |
| Invalid upload | Corrupt file, image over 20 MP or file over 10 MB | Clear rejection without ingestion |

Two-aspect example: `Describe el hábitat y la alimentación de las especies candidatas recuperadas, según las fuentes. No confirmes la especie de la fotografía.`

Open each citation and compare its quote with the source excerpt. In **Cómo se ha construido esta respuesta**, inspect model revision, state, request ID, context and runtime. `answered`, `partial`, `abstained` and `error` differ: a timeout/invalid JSON is a technical failure, not evidence that the corpus is empty. An unrelated image can still retrieve plausible candidates; nearest-neighbour retrieval is not a calibrated out-of-distribution detector.

## 6. Repeat acceptance

```bash
# Existing corpus only: read originals and query an independent snapshot.
python -m orchestration.validate_reference --models
# Real Qwen/BLIP acceptance; allow several minutes on CPU.
python -m orchestration.validate_rag --run
```

`validate_reference --task3` checks the retained BLIP captioning baseline; **`validate_rag` checks the complete RAG**. Native-model checks are outside ordinary CI because of hardware/cache requirements. See [validation](testing_and_validation.md) and [versioned evidence](evidence/README.md).

## 7. Troubleshoot and stop

| Symptom | Action |
|---|---|
| Storage unavailable | Check Docker, `.env` and `python orchestration/check_minio_connection.py` |
| Missing search index | Create an independent snapshot after indexing |
| Missing model | Run the explicit online preparation commands |
| Insufficient RAM | Close unused applications; avoid concurrent inference |
| `generation_timeout` | Inspect context/runtime; retry after freeing resources |
| Port in use | Stop your previous backend or use `--port 8766` |
| GitHub check fails | Read job logs and JUnit/coverage artifacts before submission |

Stop the web process with Ctrl+C. Stop only test storage with `docker compose -p ecosentinel-tests -f docker-compose.test.yml down`. Never run `docker compose down -v` against the reference project. Commit source, configuration, documentation and the report; keep `.env`, data, weights and runtime outputs local.
