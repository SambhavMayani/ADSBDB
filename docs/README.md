# EcoSentinel documentation

Reference installation: **198 accepted assets and 6,021 embeddings**. Commands use Python 3.11 and Git Bash; inference runs on CPU.

This page indexes the technical documentation. The [repository README](../README.md) provides the project overview and quick start.

## Start here

- [User guide](user_guide.md): installation, fresh-clone setup, interface cases and expected outcomes.
- [Project report](ecosentinel_report.pdf): design, results and limitations.

## Reading order

1. Read the [repository README](../README.md) for the purpose, architecture and execution sequence.
2. Read the [project report](ecosentinel_report.pdf) for the design choices and recorded results.
3. Follow the [user guide](user_guide.md) when installing or running the application.
4. For implementation details, follow the technical references below from Landing to Exploitation, then Tasks 1/2 and Task 3. Orchestration explains how the stages connect.
5. Use [testing and validation](testing_and_validation.md) to reproduce checks and understand what the recorded results establish.

## Technical references

| Responsibility | Maintained reference |
|---|---|
| Acquire and preserve originals | [Landing](landing_zone_documentation.md) |
| Standardise representations | [Formatted](formatted_zone_documentation.md) |
| Evaluate quality and duplicates | [Trusted](trusted_zone_documentation.md) |
| Segment, encode and persist vectors | [Exploitation](exploitation_zone_documentation.md) |
| Retrieve within and across modalities | [Tasks 1 and 2](multimodal_tasks_documentation.md) |
| Generate with retrieved evidence | [Task 3 / RAG](generative_tasks_documentation.md) |
| Execute, recover and reconcile | [Orchestration](pipeline_orchestration.md) |

## Decisions and validation

- [Architecture decisions](decision_log.md): current choices, rationale and tradeoffs.
- [Testing and validation](testing_and_validation.md): reproducible checks, adversarial cases, results and limits.
- [Data and model provenance](data_sources.md): sources, licences, model choices and corpus handoff.
- [Selected evidence](evidence/README.md): portable summaries, complete runtime reports remain local and ignored.
