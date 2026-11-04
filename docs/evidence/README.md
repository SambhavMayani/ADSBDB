# Versioned assessment evidence

Small summaries for assessment, without secrets, raw media, model weights or full retrieved passages. Complete logs, JUnit and coverage XML stay under ignored `reports/validation/`. GitHub Actions uploads its own test artifacts.

## Current review

The **4 November 2026** `submission_review` in [final_validation.json](final_validation.json) maps the official P1 constraints to the implementation and records final verification. The offline suite passes **469 tests with 72.37% statement coverage**, and isolated real S3/Chroma integration passes with two pipeline runs. Dependency consistency, Ruff and formatting also pass. Native model inference and production data processing are not rerun.

The report has eight numbered content pages, two initial manual pages, one cover and appendix A1, making twelve physical pages. Query routes are checked against the code, including image preparation, BLIP/domain screening, retrieval, generation and storage access. The [requirements mapping](../p1_requirements.md) states how this length relates to the official limit and the authors' reported allowance. Source and final PDF are maintained together.

The earlier `report_rationale_review` records the same day's first document revision. Its artifact hashes belong to that revision. The subsequent submission review records the final artifacts and new test runs rather than overwriting historical evidence.

## Evidence files

| File | Scope |
|---|---|
| [Quality images](quality_images.json) | Reference report from 19 October 2026, 100 images |
| [Quality audio](quality_audio.json) | Reference dataset, 34 recordings |
| [Quality text](quality_text.json) | Reference dataset, 64 descriptions |
| [Native models](native_models.json) | Five real CLI RAG cases and one separate browser case on 24 October, not an accuracy benchmark |
| [Final validation](final_validation.json) | Dated reviews, test outcomes, preservation checks and artifact hashes |
| [Presentation examples](../presentation/task_examples.json) | Recorded retrieval examples and source attribution |

Quality summaries identify their report and evaluation scope. Synthetic fixtures test failure cases but do not describe the wildlife dataset. Complete source fields do not establish correct attribution or taxonomy. Statement coverage measures executed code, not retrieval accuracy or requirement completion. Model revisions, limits and historical inference cases remain explicit.

## Remote CI and reproduction

[Actions run 41820793368](https://github.com/SambhavMayani/ADSBDB/actions/runs/41820793368) was checked on 4 November and passed for commit `d470f07` in Windows/Linux offline and Linux storage jobs. The commit identifies the exact repository version tested, rather than the date of every later documentation edit. Recheck the submitted revision after publishing changes. Earlier run IDs remain in the historical JSON entries.

Use the [user guide](../user_guide.md) for installation and the [validation guide](../testing_and_validation.md) for commands and expected results. Offline tests need no reference data. Exact reproduction of the 198 assets and 6,021 vectors requires the matching data/metadata handoff and pinned model cache.

## Historical records

Earlier entries in the JSON retain their original dates and scopes. These include preservation inventories, synthetic CPU runs, native-model acceptance, query-preparation changes and the 29 October coverage expansion from 68.17% to 72.37%. Previous report hashes and page counts describe superseded revisions. The presentation's last validated revision has 25 slides, a 2,022-word speech and an estimated 18:25 rehearsal target, with matching notes and two preserved chart workbooks. No new PowerPoint validation is claimed by this report review.
