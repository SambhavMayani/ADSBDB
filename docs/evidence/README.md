# Versioned assessment evidence

Small, reviewable summaries without secrets, raw media, model weights or complete retrieved passages. Runtime logs, JUnit and coverage XML remain under ignored `reports/validation/`; GitHub Actions uploads its own artifacts.

| File | Scope |
|---|---|
| [Quality images](quality_images.json) | Reference report from 19 October 2026: 100 images |
| [Quality audio](quality_audio.json) | Reference corpus: 34 recordings |
| [Quality text](quality_text.json) | Reference corpus: 64 descriptions |
| [Native models](native_models.json) | Five real CLI RAG cases and one separate browser case on 24 October; not an accuracy benchmark |
| [Final validation](final_validation.json) | Final-review tests, CPU smoke counters and preservation checks |

Quality summaries name their local report and evaluation scope. Later synthetic reports do not describe the wildlife corpus. Field completeness does not establish truthful attribution or correct taxonomy.

Native-model evidence records the tested model revision and policy. The few structural and qualitative checks are not a held-out biological benchmark. Final review preserves that inference configuration and adds code, storage and failure-boundary checks.

Local evidence does not assert that GitHub CI passed. Verify the remote workflow against the submitted commit. Reproduction commands are in the [user guide](../user_guide.md) and [validation history](../testing_and_validation.md).

The subsequent input-boundary review is embedded in final_validation.json: 20 additional regressions, 364 offline tests, one isolated integration test, and 71.82% combined statement coverage. Earlier native-model and corpus-preservation records remain separately dated. Complete qualitative retrieval rankings and photo attribution are in [presentation/task_examples.json](../presentation/task_examples.json).

The historical `documentation_review` entry records the then-current one-page instructions plus eight-page report, all-page visual inspection, Git Bash syntax and read-only CLI checks. Its report/manual hashes describe that revision. Top-level artifact hashes also belong to the earlier dated execution review; they are preserved as historical evidence. Documentation checks do not rerun acquisition, model preparation or the production pipeline.

The preceding `similarity_documentation_review` records the compact eight-page report and retrieval-guide hashes. Its report page 6 expanded cosine arithmetic, HNSW/exact scanning, space compatibility and rank fusion; the other eight physical pages rendered identically to its predecessor. Isolated pure-function checks verified cosine examples, invalid-vector rejection and RRF arithmetic without opening storage or loading models.

The preceding `report_expansion_review` records the nine-page report plus separate instructions. It uses the professor's allowance for substantive expansion as relayed by the authors. A dedicated methods page gives the formula, examples, indexing algorithm, space compatibility and rank fusion; the Tasks/interface page restores fuller explanations and includes top-k controls. All ten physical pages of that revision were visually reviewed with unchanged body typography.

The latest `report_trusted_review` contains the current report hashes: ten numbered pages including the cover, plus the separate instructions page. Report page 5 explicitly documents per-asset manifests, HTML/JSON/CSV/PNG roles, dated output folders, modality-specific measurements, histogram/bar-chart purposes, descriptive statistics and interpretation limits. All earlier section bodies were retained; cover contents and page references were updated. All eleven physical pages were visually reviewed with unchanged body typography. The report page was checked against both reporting generators without executing them or accessing storage. The document index and requirement mapping record the current length.

The latest `presentation_revision_review` supersedes the historical `presentation_review`: 24 slides, a 15:00 rehearsal target and a 25-page English script. It records current artifact hashes, visual inspection, matching speech/notes, package/layout/import checks and preservation of both original chart workbooks. Four illustrated name/content cases were checked against the isolated actual Landing key-builder function. The HNSW explanation was cross-checked against code and the supplied course slides; its graph is conceptual. Cosine arithmetic is illustrative; displayed Task 1/2 scores come from the existing retrieval evidence. All earlier slide speeches and the pipeline graphic were preserved. Native PowerPoint rendering remains a separate classroom check. This revision did not rerun models or open project data stores.
