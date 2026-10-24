# EcoSentinel user and assessor guide

Run these commands in **Git Bash**, at the repository root, with `.venv` activated. The [README](../README.md) covers installation. This guide distinguishes a fresh clone from the authors' reference installation.

A **dataset** is the collection of image, audio and text files. **Embeddings** are the numeric representations generated from those files or their segments. The vector index stores embeddings and source references; the original media remain in object storage.

Choose the route matching what you actually received:

| Starting point | Route and prerequisites |
|---|---|
| Code only | Run section 1 immediately. For wildlife queries, first obtain raw files/metadata or configure explicit acquisition, then prepare models and follow section 3. |
| Raw files plus `_metadata.json` sidecars | In a new clone, retain `data/raw_dataset/<modality>/<species_id>/`; prepare models and local storage, then execute the complete section 3 sequence. |
| Already prepared, matching S3 state and Chroma index | Prepare local credentials/models, verify with reconciliation, then follow section 4. The index alone does not provide the source media. |
| Existing installation with its query copy | Start storage and the web; reuse the copy if the dataset has not changed. |

The first PDF page provides the condensed procedure; this guide contains the full branches. A dataset transfer must retain provenance and applicable licences. No download link or prepared storage backup is distributed by the code repository. Exact reference evaluation requires access arranged with the authors; new acquisition is a separate route with variable results.

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

Dependency installation, model downloads and wildlife acquisition are separate operations. **Preparing models** means downloading files containing already trained model parameters (weights) and checking that the application can use them. Libraries installed by `pip` provide the executable code; the weights provide the learned parameters used during inference. Those large files are not included in Git or necessarily installed by `pip`. No training is performed, and this step neither acquires animal files nor computes dataset embeddings.

**Do this before the first complete pipeline run.** Exploitation needs CLIP, multilingual CLIP, CLAP and E5 to create the vector representations. Pipeline subprocesses default to offline model loading: `--with-acquisition` does **not** enable model downloads. Reuse the cached weights on subsequent runs. Qwen and BLIP are separate prerequisites for Task 3; they are not needed to build the zones or use Tasks 1 and 2.

Prepare the embedding models once while online, then verify local loading:

```bash
python -m exploitation_zone.prepare_models --download
python -m exploitation_zone.prepare_models
```

Expected: `Embedding models ready; no objects or embeddings were created.` Preparation loads the model families sequentially on CPU and releases them; it can take time and requires available RAM. Model IDs and pinned revisions come from `config/exploitation.yaml` and `config/model_manifest.json`.

For Task 3, also prepare Qwen and, for questions with images, BLIP:

```bash
python -m multimodal_tasks.rag_model --download
python -m multimodal_tasks.rag_model
# BLIP: download the pinned files without an index or a query.
HF_HUB_OFFLINE=0 python -c "from huggingface_hub import snapshot_download; from multimodal_tasks.generate import MODEL, REVISION; snapshot_download(repo_id=MODEL, revision=REVISION, token=False)"
```

Expected: Qwen prints `RAG model ready` after verifying the configured GGUF SHA-256; the BLIP command prints its cached directory. Qwen is stored under `data/model_cache/gguf/`. Embedding models and BLIP use the Hugging Face cache, normally `~/.cache/huggingface/hub/`, unless its environment settings override it. Keep that cache available to the same user who runs the pipeline/web.

Existing cache files are reused; these commands do not force an index rebuild. Later ordinary queries load locally. Keep several GiB free on disk for the weights and available RAM for inference. Qwen checks for at least **2.5 GiB available RAM** before loading. CPU requests can take minutes; the 120-second generation deadline excludes retrieval and model loading. If weights are missing, reconnect and repeat preparation; do not delete the vector index. Downloads are needed again only if required files are absent or the configured model revision changes.

| Operation | Internet and local effects |
|---|---|
| Install dependencies | Downloads libraries into `.venv`; not wildlife data or a populated index |
| Prepare models | Downloads pretrained weights into local caches; no data-zone writes or dataset embeddings |
| Acquire wildlife | Contacts configured providers and saves raw files plus provenance metadata |
| Run zones and index | Reads local raw data and cached weights; writes local S3 zones, reports and Chroma |
| Query | Reads the query index, local S3 media and cached models; no new wildlife acquisition |

The ordinary pipeline still requires the local S3 service even when no Internet acquisition is requested. Model installation and wildlife acquisition are the explicit online setup operations; the reference application does not require a paid remote inference API.

## 3. Fresh clone without the reference data

The repository excludes the authors' MinIO volume and 6,021-vector index. Choose **A or B** for wildlife data, then continue to section 4. The synthetic demonstration below is an optional technical check, not a prerequisite or a replacement for the wildlife dataset.

**Technical demonstration.** With the test service running and embedding weights cached:

```bash
python -m orchestration.smoke --run --workdir data/assessor-smoke
python -m orchestration.smoke --run --workdir data/assessor-smoke
```

Use a new folder for the first run, then intentionally reuse it. Expected: three synthetic assets, seven embeddings, reconciliation success; zero new vectors on repetition. This exercises real subprocesses, decoders, S3, Chroma and CPU models. The image is noise and the audio is a tone: this proves execution, **not wildlife relevance**. Reports are in that folder's `reports/` directory. If the ephemeral test service is recreated, choose a new smoke directory.

### Common storage setup for routes A and B

After installation and embedding-model preparation, create `.env` only if it is absent. Edit it locally: `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` must match the Docker service; `S3_ENDPOINT_URL` defaults to `http://127.0.0.1:9000`. Do not replace an existing installation's credentials. Docker Desktop must be running.

```bash
cp -n .env.example .env
# Edit .env locally before starting a new service; never commit it.
docker compose up -d
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:9000/minio/health/ready
python orchestration/check_minio_connection.py
```

Expected: a successful health request and `Connection to object storage successful`. The pipeline creates any missing buckets. Do not continue if authentication or connectivity fails. The Console at port 9001 is for storage inspection, not the project interface.

### A. No local raw files: acquire and process wildlife

Keep Internet access available. Review the species/source selection in `config/species.yaml`. Obtain a Xeno-canto API key from that provider and set `XENO_CANTO_API_KEY` in the untracked `.env`; a blank example value is insufficient. The current Wikimedia and Wikipedia/GBIF adapters do not require a configured API key. Then run:

```bash
python -m orchestration.pipeline --plan --with-acquisition
python -m orchestration.pipeline --run --with-acquisition
```

The plan must list **19 steps**, beginning with storage checks, then three downloads before ingestion. The run downloads raw files and metadata into `data/raw_dataset/`, processes all zones, indexes the accepted assets and reconciles the result. APIs, rate limits, available records and network failures can change the outcome: a fresh acquisition does not promise 198 assets or 6,021 vectors. Exact offline reproduction requires the original data handoff and cached weights; Git alone is insufficient. See [data sources](data_sources.md).

The flag schedules the existing acquisition scripts before ingestion; it does not change the remaining zone order:

| Data | Script invoked by the orchestrator |
|---|---|
| Images | `landing_zone/data_acquisition/download_wikimedia_images.py` |
| Audio | `landing_zone/data_acquisition/download_xeno_canto_audio.py` |
| Text | `landing_zone/data_acquisition/download_species_texts.py` |

There is no need to invoke these individually when using `--with-acquisition`. Each adapter writes files and `_metadata.json` under its modality/species directories. Inspect the acquisition logs and downloaded metadata; a command that exits successfully is not proof that every requested species was available. The final reconciliation checks consistency, not a promised acquisition quota. Continue to section 4 only after checking completion and that the intended modalities contain accepted assets.

If a download fails, the pipeline stops and records the failed step. Fix the provider key, connectivity or reported API problem, then repeat the same acquisition-enabled command; the adapters reuse existing files according to their metadata. Do not delete the data or index as a recovery step. Once the intended raw dataset is complete, subsequent processing can use route B without further wildlife downloads.

**Acquisition targets are not acceptance guarantees.** The orchestrator uses each script's defaults: images target ten per configured species; audio targets four per species and exits with failure if the overall target is not reached. Therefore an API that cannot supply enough recordings can stop route A even when some valid audio files were saved. Inspect the `download-audio` log and retained metadata. If a smaller dataset is appropriate, explicitly document the reduced scope and use route B on the reviewed local files; do not present that run as an exact reproduction of the reference. For deliberate acquisition settings, invoke the individual adapters with their documented CLI options before route B (`python landing_zone/data_acquisition/download_xeno_canto_audio.py --help`, for example). The pipeline flag does not forward custom per-adapter limits.

### B. Raw files already local: process without acquisition

Complete model preparation and the common storage setup above. Preserve the supplied directory structure and `_metadata.json` sidecars:

```text
data/raw_dataset/
  images/<species_id>/   image files and _metadata.json
  audio/<species_id>/    recordings and _metadata.json
  text/<species_id>/     text files and _metadata.json
```

Use the IDs in `config/species.yaml`. Sidecars retain source identity, filenames, attribution, licences and hashes; copying arbitrary media without the expected metadata does not reproduce the acquisition output. Before processing, inspect that the files referenced by the supplied metadata are present. Then execute:

```bash
python -m orchestration.pipeline --plan
python -m orchestration.pipeline --run
```

Expected: a **16-step** plan, then `Pipeline status: completed` with final reconciliation of Trusted and the original Chroma index. The normal `--run` uses local inputs without acquiring wildlife from the Internet. Continue to section 4 for verification, the query copy and web startup. If there are no usable raw assets, resolve that input problem rather than treating an empty run as a completed wildlife demonstration.

## 4. Start the reference interface

**C. Already prepared storage and original index:** skip route A/B and avoid rerunning the pipeline unnecessarily. Use matching S3 data, index and cached models. Start storage and run the read-only checks below. After a new build through A/B, use these checks too, but compare counts with that build's outputs rather than assuming the authors' reference totals:

```bash
docker compose up -d
python -m orchestration.reconcile
python -m orchestration.audit --source data/chromadb
```

Only for the unchanged reference installation, expected collection counts are images 100, audio 357, text 547, image-text 1,763, audio-text 3,254; total 6,021. Reconciliation must report `status: completed` and `problems: []`. With index writers stopped, create a snapshot only if it does not exist:

```bash
python -m orchestration.audit --source data/chromadb --snapshot data/search_index
python -m multimodal_tasks.search --status
python -m webapp.server
```

Open **http://127.0.0.1:8765**. A query snapshot is a verified copy of the already built vector database:

```text
data/chromadb/       original index built by the pipeline
        |
        | copy existing database files and verify their hashes
        v
data/search_index/   independent copy opened by search and the web
```

Creating it does not run encoders, regenerate embeddings or duplicate source photographs/recordings. Source media still come from object storage. Search refuses to open the original index, protecting it from Chroma startup migrations and internal writes. The pipeline does not create the snapshot or launch the web automatically.

**Persistence and copying serve different purposes.** Chroma already persists the index in `data/chromadb/`; restarting Python does not require rebuilding it. The extra query copy is our conservative preservation policy for the audited original, not a technical requirement of persistence. It duplicates database files and costs disk space. A service with coordinated access to a single persistent index would be another design; this prototype deliberately rejects the original path in `SearchService`.

The snapshot command refuses to overwrite an existing folder. A snapshot reflects its creation time and does not synchronise with later pipeline changes. To refresh, choose a new path and start `python -m webapp.server --index NEW_PATH`. After code updates, stop the old backend with Ctrl+C, restart it and refresh with Ctrl+F5.

For example, stop the old web process and all index writers, then use an unused destination:

```bash
python -m orchestration.audit --source data/chromadb --snapshot data/search_index_review_02
python -m webapp.server --index data/search_index_review_02
```

If that folder already exists, select another new name. Keep the previous copy for inspection; no deletion is needed to refresh. A source-change/hash error during copying means the result is not a verified snapshot: stop writers, investigate and repeat with a new destination. It never means the original should be rebuilt automatically.

### Expected outputs and completion

The complete pipeline must print `Pipeline status: completed`. Its final reconciliation should report `status: completed` and `problems: []`; unchanged reference data should retain 198 accepted assets and 6,021 vectors. Compatible re-execution should add zero vectors, while new logs and reports can still be created. Pipeline completion does not start the web.

| Output | Where to inspect it |
|---|---|
| Pipeline status, timings and step errors | `reports/orchestration/pipeline_<run>.json` and the step `.log` files in the same directory |
| Trusted quality report by modality | `reports/trusted_quality/<modality>/<timestamp>/quality_report.html` |
| Aggregate/per-file metrics and plots | `summary.json`, `metrics.csv` and `.png` files alongside that HTML; keep them together |
| Per-asset acceptance decisions | S3 bucket `trusted-zone`, prefix `_quality/` |
| Persisted original vectors / query copy | `data/chromadb/` / the selected snapshot directory |

MinIO/S3 Console is at **http://127.0.0.1:9001** with the locally configured credentials; the project interface is at **http://127.0.0.1:8765**. They are separate applications. Default paths above assume no storage/report environment overrides.

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

## 7. Short demonstration route

With the interface and models ready, show a stored-image Task 1 query, then image-text Task 2 with “Iberian lynx in its natural habitat”. Open the provenance of one image and one text. For Task 3, inspect the recorded frog example and its citations; offer live CPU generation after the timed talk. End with an unsupported request and the harmless security demonstration:

```bash
python tests/demo_security_gate.py
python -m pytest tests/test_input_boundaries.py tests/test_trusted_images.py -q
```

Expected: the synthetic executable header is blocked; no executable runs or uploads. Tests generate their own edge cases. See [validation](testing_and_validation.md) for the policy matrix and limits. The [presentation](presentation/README.md) contains the timed English script.

## 8. Troubleshoot and stop

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
