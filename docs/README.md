# EcoSentinel documentation

Reference installation: **198 accepted assets and 6,021 embeddings**. Commands use Python 3.11 and Git Bash; inference runs on CPU.

## Start here

1. [Project report](ecosentinel_report.pdf): domain, purpose, architecture, justified choices and Tasks 1–3. Eight numbered content pages, a separate cover and a two-page user manual (eleven physical pages). Plain English explains the decisions, Trusted reports, similarity and all three Tasks. [Editable LaTeX source](report/main.tex).
2. [User and assessor guide](user_guide.md): installation, fresh-clone setup, interface cases and expected outcomes.
3. [P1 requirements](p1_requirements.md): mapping from the statement to implementation and evidence.
4. [Presentation and script](presentation/README.md): English group defence with real examples and speaking notes.

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
- [Selected evidence](evidence/README.md): portable summaries; complete runtime reports remain local and ignored.

The report gives the narrative; the user guide gives the procedure; technical references define each component. Historical audit and duplicate demo instructions have been consolidated into these maintained documents. Git retains their history.

Original data, model weights, runtime reports and secrets do not belong in Git. Queries use an independent Chroma snapshot. Tests use generated inputs and isolated storage rather than the reference MinIO service. Update the relevant reference when behavior changes and record measured outcomes separately from configured capabilities.

## Building the LaTeX report

The maintained source is `docs/report/main.tex`; the pipeline diagram and tables are native LaTeX. No external authoring script is required. The PDF contains eight numbered content pages, preceded by two unnumbered manual pages and a separate cover. `final_report.md` is only a compatibility link.

Install a LaTeX distribution separately from the application's Python dependencies. With Tectonic (the reviewed build used 0.17.0), run from the repository root in Git Bash:

```bash
mkdir -p reports/validation/latex
tectonic --keep-logs --outdir reports/validation/latex docs/report/main.tex
cp reports/validation/latex/main.pdf docs/ecosentinel_report.pdf
```

Tectonic may download TeX packages on the first build. A standard distribution can instead run `pdflatex -halt-on-error -interaction=nonstopmode -output-directory=reports/validation/latex docs/report/main.tex` twice, followed by the same copy command. The source uses standard packages including TikZ, PGFPlots, Latin Modern, amsmath and xurl. Review page count and layout after content changes. Keep both the TeX and the compiled PDF in Git; keep intermediate files under ignored `reports/validation/`.
