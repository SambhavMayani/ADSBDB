# EcoSentinel testing and validation

Current local review: **24 October 2026, Windows, Python 3.11.2, CPU**. Commands below are for Git Bash at the repository root with the virtual environment active. [Selected evidence](evidence/README.md) is versioned; complete generated reports stay local and ignored. This page replaces the chronological development log.

## 1. Measured results

| Check | Observed result | Local evidence |
|---|---|---|
| Offline regression | **364 passed, 1 integration test deselected** | reports/validation/inputs_offline.xml |
| Isolated real S3 + Chroma integration | **1 passed, 364 deselected**, two pipeline passes | reports/validation/inputs_integration.xml |
| Offline statement coverage | **64.40%**, 3,393 / 5,269 statements | inputs_coverage.xml |
| Combined statement coverage | **71.82%**, 3,784 / 5,269 statements | inputs_coverage_combined.xml |
| Real CPU CLI, recorded delivery smoke | **16/16 steps**, three synthetic assets, seven vectors | delivery_smoke_first.log |
| Repeated real CPU CLI | **16/16 steps**, zero new vectors in all five spaces | delivery_smoke_repeat.log |
| Real generative acceptance | **5/5 structural cases**, plus a separate frog web case | frog_acceptance_final.json; frog_ui_validation.json |
| Original Chroma preservation | Same filenames, byte sizes and SHA-256; **6,021 vectors** | delivery_preservation.json; presentation_examples/retrieval_examples.json |
| Original MinIO preservation | Same keys, sizes and ETags; **396 / 198 / 396 objects** | delivery_minio_preservation.json |

Coverage measures executed statements, **not retrieval accuracy, biological correctness or the percentage of requirements completed**. Offline and combined figures have different execution scopes. Real-model CLI runs are outside pytest and are not added to coverage. The report PDF and this page include the 20 additional regressions recorded in the input-boundary review of [final_validation.json](evidence/final_validation.json); earlier execution records remain separately dated.

## 2. Fast verification without the reference corpus

```bash
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m orchestration.pipeline --plan
```

The plan has 16 steps and performs no storage or model work. Tests generate their own files and use temporary indexes, controlled encoders and local HTTP. The automatic fixture blocks external connections and production MinIO ports 9000/9001, disables model downloads and removes the security webhook setting. There are no hidden model downloads or private-data requirements.

To measure offline coverage using the same denominator as CI:

```bash
python -m pytest -q --cov=orchestration --cov=exploitation_zone --cov=trusted_zone --cov=formatted_zone --cov=landing_zone --cov=multimodal_tasks --cov=webapp --cov-report=xml:reports/validation/coverage.xml --junitxml=reports/validation/offline.xml
```

## 3. Failure cases and adversarial inputs

A clean reference corpus alone cannot demonstrate robust rejection. These tests use synthetic failures and assert the resulting state, including what must remain unchanged.

| Case | Expected behavior and evidence |
|---|---|
| Executable extension or MZ header disguised as JPEG | Block before hashing/upload; tests/test_trusted_images.py |
| ELF, Mach-O and OLE headers disguised as text | Block as active/binary input; tests/test_input_boundaries.py |
| Empty image, audio or text | Explicit empty-file rejection |
| PNG renamed JPEG; JPEG header with invalid content | Signature mismatch or invalid image structure |
| Decodable image above pixel budget | Block before conversion; size and pixel limits are independent |
| DOCX expansion ratio, uncompressed size or entry-count limit | Reject without extracting; a few KiB suffice for the generated fixtures |
| Corrupt/truncated Formatted JPEG | Quality rejection with a reason; no accepted output published |
| Replacement of an accepted image by corrupt bytes | Keep prior accepted bytes; record the current rejection |
| Possible watermark | Keep bytes and record the warning; the policy test injects a controlled signal |
| Corner-edge heuristic and unavailable OCR | Exercise actual lightweight analysis and explicit OCR fallback; no claim of watermark detection accuracy |
| Dark image, silent/quiet audio, Unicode and privacy-like text | Preserve useful data according to the modality policy; warnings remain visible |
| Exact/near duplicates and cross-species conflicts | Apply explicit modality scope; record links and reasons |
| Copy mismatch, failed marker, partial vector upsert | Stop safely, preserve prior state, recover on compatible rerun |
| Concurrent writers, child timeout, Unicode logs | Reject conflicting runs, terminate owned children, preserve readable diagnostics |
| Invalid policy, non-finite vector, missing/duplicate segment | Reject incompatible publication rather than trusting counts alone |
| Invalid citations, incomplete JSON, missing weights or RAM | Separate technical error from abstention; reject unsupported output and release resources |

Focused reproduction:

```bash
python tests/demo_security_gate.py
python -m pytest tests/test_input_boundaries.py tests/test_trusted_images.py tests/test_trusted_audio_text.py tests/test_safety_regressions.py -q
```

The demo writes harmless header bytes only in a temporary directory. It does not create or run a working executable, upload files or contact storage. Expected output: BLOCKED / executable_or_active_binary_detected. Security Gate is bounded screening, not antivirus or proof of safety. No finite suite covers every possible malicious file.

The new corruption regression exposed a classification bug: Pillow decoding failures inherited OSError and looked like storage failures. Only decoding inside the pure image analyzer now normalises that failure to a quality rejection. S3/read errors remain operational failures; both paths preserve previous accepted objects. No existing corpus was revalidated or rewritten to make this correction.

## 4. Real storage integration and full CPU execution

```bash
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
curl --fail --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:19000/minio/health/ready
python -m pytest -m integration -q
```

The fixture uses the separate port 19000, disposable credentials, UUID-owned buckets and temporary Chroma. It cleans only its own buckets. Deterministic encoders keep the contract test independent of model caches; the second pass verifies no additional encoder calls or vectors. To combine coverage, run it after the offline command with the same --cov options plus --cov-append and a separate output path.

With cached embedding weights, the [user guide](user_guide.md) explains the stronger subprocess/decoder/model check:

```bash
python -m orchestration.smoke --run --workdir data/assessor-smoke
python -m orchestration.smoke --run --workdir data/assessor-smoke
```

Choose a new folder for a new ephemeral storage session, then reuse it for the second pass. Expected: three synthetic assets, seven vectors, then zero new vectors. Noise and tone fixtures prove execution and reuse, not wildlife relevance. The recorded first run has an unexplained 11,932.701-second text-index interval; it is not presented as typical latency or a performance benchmark.

## 5. Corpus, retrieval and RAG acceptance

```bash
python -m orchestration.validate_reference --models
python -m orchestration.validate_rag --run
```

These opt-in checks require the reference corpus and cached weights. They read the original index through read-only SQLite and query an independent copy. Reference acceptance also checks compatible reuse without encoder inference. The earlier 460 asset/collection compatibility checks all passed. An S3 inventory comparison is by key/size/ETag, not a new full download/hash of every original.

The [presentation examples](presentation/task_examples.json) record a real image-to-image lynx query and a text-to-image/text query. They retain the complete ranked asset lists and selected photo attribution. Four of five image hits have lynx catalogue labels and one has a wolf label; a cropped near duplicate survives. These are inspectable qualitative examples, not an accuracy benchmark.

Real RAG cases cover lynx habitat, a lynx image, a frog candidate, a complete-genome request and an out-of-domain pizza request. The separate multipart frog browser case produced habitat and diet claims with inspected source extracts. The original external frog photograph was not available for that recorded validation; a Trusted frog image was used. English slide extracts translate the Spanish output. A cited lynx response was less direct than desired, so a structural pass is not described as perfect semantic accuracy. [Native-model evidence](evidence/native_models.json) records scope and limitations.

For UI validation, follow the [case table](user_guide.md) and inspect the state, request trace and literal quote behind each citation. Unrelated images can still produce plausible nearest neighbours; no calibrated out-of-distribution or species-identification guarantee is claimed.

## 6. Quality reports, CI and delivery limits

Trusted validators write per-asset manifests. Report generators aggregate these into HTML, CSV, JSON and distribution plots without re-reading original image bytes. [Quality summaries](evidence/README.md) preserve results: 100 images retained, 32 possible watermark warnings, complete measured provenance and zero observed image species-distribution shift. These are processing and metadata metrics, not biological accuracy or proof that all files lack overlays. The [presentation chart data](presentation/quality_charts.json) records the species series and audio bins derived from these existing reports; slide preparation does not revalidate the corpus. See [Trusted](trusted_zone_documentation.md).

**GitHub Actions is GitHub's automated test service.** The versioned configuration is [quality.yml](../.github/workflows/quality.yml). A push or pull request starts checks on fresh Windows and Linux machines: install the same requirements, check dependencies and code style, and run the offline suite. A separate Linux job tests real S3/Chroma integration using isolated test storage. These checks use generated fixtures rather than the authors' local data or secrets. They do not publish or deploy the application. Native-model tests remain explicit local checks because cached weights, memory and timings vary.

The **60% coverage threshold** means the offline tests must execute at least 60% of the measured code statements. It is a minimum regression guard, not a model-accuracy score or a grade. The measured local offline coverage is 64.40%; 71.82% includes the separate integration run. Test-result XML (JUnit) and coverage reports are saved as downloadable files, called **artifacts** in GitHub.

GitHub enables Actions by default, but a repository or organisation can restrict or disable it. Availability alone does not define project tests: our workflow file supplies those instructions. Once that file is pushed and permitted, future pushes trigger checks automatically; no per-push activation is needed. If disabled, a repository administrator can review **Settings → Actions → General**. See [GitHub's repository settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).

After the authors push the final commit:

1. Open the repository on GitHub and select **Actions**.
2. Select **EcoSentinel quality**, then the run corresponding to that commit.
3. Confirm both Windows/Linux offline jobs and the storage integration job succeeded. A pending or running job is not yet a pass.
4. If a job failed, open the failed step and read its log. Download its reports under **Artifacts** when available, fix the reported cause and push the correction.

A local test pass does not establish that the remote checks passed. The recorded evidence does not claim success for a remote run that has not been inspected. The application can be run locally using the user guide independently of this submission check. [GitHub's overview](https://docs.github.com/en/actions/get-started/understand-github-actions) defines the service.

The final review keeps acquisition/CLIs in the coverage denominator. Remaining evaluation work includes a labelled relevance/answer benchmark, systematic peak-RAM measurement and installation on another clean machine. Native Windows process termination needs permission to stop the test's own children; a restricted execution sandbox can delay that check, so the complete suite was also run in the normal host context. No failure was hidden with a skip or a relaxed assertion.
