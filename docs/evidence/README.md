# Validation evidence

Compact summaries of technical checks and reference-corpus measurements. Complete logs, JUnit and coverage reports remain under ignored `reports/validation/`; GitHub Actions stores reports for its own runs.

| File | Scope |
|---|---|
| [Image quality](quality_images.json) | 100 reference images, measured on 19 October 2026 |
| [Audio quality](quality_audio.json) | 34 reference recordings |
| [Text quality](quality_text.json) | 64 reference descriptions |
| [Native models](native_models.json) | Five CLI RAG cases and one browser case from 24 October 2026 |
| [Validation summary](final_validation.json) | Dated regression, integration, CPU pipeline, index reuse and preservation results |

The recorded 4 November regression has **469 passing offline tests and 72.37% statement coverage**. A separate S3/Chroma integration test passes with deterministic encoders. Native-model checks and corpus preservation results retain their earlier dates; they were not repeated for subsequent query-preparation or documentation changes.

Statement coverage measures executed code, not retrieval accuracy. Quality summaries measure processing decisions and metadata completeness, not correct taxonomy or licences. The native cases are qualitative checks, not a labelled benchmark.

Use the [user guide](../user_guide.md) for installation and [testing and validation](../testing_and_validation.md) for reproduction commands and limitations. Offline tests need no reference data. Exact reproduction of the 198 assets and 6,021 vectors requires the matching dataset, metadata and pinned model cache.
