# EcoSentinel testing and validation

Commands use Python 3.11 and Git Bash from the repository root, with the virtual environment active. [Evidence summaries](evidence/README.md) are versioned; full generated reports remain local under ignored `reports/validation/`.

## Recorded results

| Check | Result | Date and scope |
|---|---|---|
| Offline regression | **469 passed, 1 integration test deselected** | 4 November 2026, Windows, Python 3.11.2 |
| Offline statement coverage | **72.37%**, 3,897 / 5,385 statements | Same regression run |
| Isolated S3 + Chroma integration | **1 passed, 469 deselected** | 4 November, two pipeline passes with deterministic encoders |
| Export without local project data | **469 passed, 1 deselected** | 4 November, empty model cache; reused installed dependencies |
| Real CPU pipeline | **16/16 steps**, three synthetic assets, seven vectors | 24 October; repeat added zero vectors |
| Reference index reuse | **460 asset/collection checks passed**, 6,021 vectors | 24 October, read-only checks |
| Native RAG | **5/5 structural cases**, plus a separate browser case | 24 October; qualitative checks |

[final_validation.json](evidence/final_validation.json) records the dated runs, local report paths and preservation checks. [native_models.json](evidence/native_models.json) records real-model cases and timing. Native inference and browser acceptance predate the query-preparation changes and were not rerun for those changes.

Coverage measures executed statements, not retrieval accuracy or requirement completion. Uncovered paths include real model adapters, acquisition, CLI wrappers and failure branches. A labelled relevance/answer benchmark, systematic peak-RAM measurements and installation on another clean machine remain evaluation work.

## Offline checks

```bash
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m orchestration.pipeline --plan
python -m orchestration.pipeline --plan --with-acquisition
```

The plans list 16 and 19 steps without connecting to storage or loading models. Tests generate their own files and use storage doubles, temporary Chroma, controlled encoders and local HTTP. The automatic fixture blocks external connections and production MinIO ports 9000/9001, disables model downloads and removes the security webhook setting.

To measure offline coverage using the same packages as CI:

```bash
python -m pytest -q --cov=orchestration --cov=exploitation_zone --cov=trusted_zone --cov=formatted_zone --cov=landing_zone --cov=multimodal_tasks --cov=webapp --cov-report=xml:reports/validation/coverage.xml --junitxml=reports/validation/offline.xml
```

## Failure cases

| Area | Assertions |
|---|---|
| Input screening | Executable headers disguised as media, mismatched signatures, empty/corrupt files, pixel budgets and DOCX expansion limits are rejected before publication |
| Quality policies | Dark images, quiet audio and privacy-like text retain the configured warnings; exact/near duplicates follow modality-specific rules |
| Recovery | Copy mismatch, failed markers, storage failures and partial vector publication preserve earlier outputs and recover on a compatible rerun |
| Index contracts | Invalid policies, non-finite vectors and missing/duplicate segments cannot be treated as complete publication |
| Search | Filters, asset grouping and exact/HNSW routing at 64/65 eligible vectors are checked |
| External queries | Formatted conversions match corpus processing; quality warnings remain non-blocking; malformed input and resource violations return explicit errors |
| RAG | Retrieval precedes generation; invalid IDs/quotes, incomplete JSON, missing weights, memory limits and concurrency produce distinct outcomes |
| Orchestration | Writer locks, child timeouts, interruption and UTF-8 logs are checked |

Focused reproduction:

```bash
python -m pytest tests/test_input_boundaries.py tests/test_trusted_images.py tests/test_trusted_audio_text.py tests/test_safety_regressions.py -q
python -m pytest tests/test_storage_boundaries.py tests/test_query_preparation.py tests/test_rag.py -q
```

Synthetic executable headers are inert test bytes; no executable is run. The Security Gate performs bounded screening rather than antivirus analysis. Storage failures and quality rejections remain separate, and both preserve previously accepted bytes.

## Storage integration and CPU execution

```bash
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:19000/minio/health/ready
python -m pytest -m integration -q
docker compose -p ecosentinel-tests -f docker-compose.test.yml down
```

The fixture uses port 19000, disposable credentials, UUID-owned buckets and temporary Chroma. It cleans only its own buckets. Deterministic encoders keep this contract check independent of cached models; the second pass verifies no additional encoder calls or vectors.

With the test service running and embedding weights cached, run the real CLI with synthetic assets:

```bash
python -m orchestration.smoke --run --workdir data/acceptance-smoke
python -m orchestration.smoke --run --workdir data/acceptance-smoke
```

Choose a new folder for a new storage session, then reuse it for the second pass. Expected: three assets, seven vectors, then zero new vectors. Synthetic noise and tones verify execution and reuse, not wildlife relevance. The recorded first run includes an unexplained 11,932.701-second text-index interval and is not a latency benchmark. See the [user guide](user_guide.md) for prerequisites.

## Reference corpus and RAG

```bash
python -m orchestration.validate_reference --models
python -m orchestration.validate_rag --run
```

These opt-in checks need the reference corpus and cached weights. They read the original index through read-only SQLite and query an independent copy. Preservation checks compare Chroma filenames, sizes and SHA-256, and S3 keys, sizes and ETags; the S3 comparison does not download and hash every original.

Native RAG cases cover lynx habitat, a stored lynx image, a frog candidate, an unsupported genome request and an unrelated pizza request. The separate frog habitat/diet browser case used a Trusted image. One lynx response was less direct than desired, so structural success does not establish semantic accuracy. For manual checks, follow the [interface cases](user_guide.md#cases-to-try-in-the-interface), compare each quote with its source and distinguish answers, partial answers, abstentions and technical errors.

Trusted report generators aggregate per-asset manifests into HTML, CSV, JSON and plots. [Quality summaries](evidence/README.md) record 100 images, 34 recordings and 64 texts retained, including 32 possible watermark warnings. Complete provenance fields and unchanged species distributions do not prove biological accuracy or correct attribution. See [Trusted](trusted_zone_documentation.md) for metric definitions.

## Continuous integration

[quality.yml](../.github/workflows/quality.yml) defines dependency checks, Ruff, formatting and offline tests on Windows/Linux, with a **60% statement coverage floor**. A separate Linux job checks isolated S3/Chroma integration. Generated fixtures replace local datasets and secrets. Native-model checks remain explicit local runs.

JUnit and coverage reports are uploaded as workflow artifacts. The evidence summary records historical CI for a specific commit; check **Actions / EcoSentinel quality** for the submitted revision. A local pass does not establish the result of a later remote run.
