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
