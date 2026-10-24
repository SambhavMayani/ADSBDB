# EcoSentinel architecture decisions

Current design, reviewed 24 October 2026. Detailed formats and commands belong in the zone guides. This register explains current choices and costs; Git preserves the earlier decision history.

| Decision | Rationale | Cost or boundary |
|---|---|---|
| Four zones with separate responsibilities | Preserve original bytes, standardise formats, evaluate quality, then encode; each stage can be inspected and retried. | More objects and explicit lineage contracts. |
| S3-compatible storage with Docker | One object API for images, recordings, documents and audit metadata. | Running storage service required; no distributed transaction with Chroma. |
| Optional acquisition with provenance sidecars | Local files and cached models support operation without provider availability. | Exact reproduction requires a data handoff; fresh downloads differ. |
| Hash plus filename as Landing identity | Repeated ingestion of the same bytes/name reuses verified completion state stored with the data. | A renamed file has a new ingest identity. Content-quality duplication belongs in Trusted. |
| Verify copy and marker before optional Temporal cleanup | Recover from partial copy or marker publication without losing input. Retain Temporal by default. | Extra verification reads; cleanup is explicit. |
| Pre-ingestion Security Gate | Check supported extensions, byte signatures, image structure, archive expansion and resource ceilings before upload. | Bounded screening is not antivirus scanning or proof of harmlessness. |
| RGB JPEG, FLAC PCM16, UTF-8 text | Predictable decoders and modality-specific processing, with raw hashes and source references. | JPEG is lossy; first-frame MPO conversion omits secondary frames from Formatted. Landing retains originals. |
| Conservative Trusted policies | Reject technical violations and confirmed duplicates; keep dark images, possible overlays and quiet recordings as warnings. | Heuristics miss near duplicates or flag natural text; thresholds are operational choices. |
| Separate safety and quality budgets | Stricter Trusted ceilings bound accepted representations: images 20 decimal MB / 40 MP / minimum 128 by 128; audio 200 MB; text 4 MB. | These limits do not measure ecological value or guarantee fixed peak RAM. |
| Modality-specific duplicate scope | Exact audio/text across species may be meaningful or expose label conflicts; image candidates need strict confirmation. | Full runs are needed for global duplication; cropped variants can survive. |
| Retain prior accepted bytes after later error/rejection | Avoid destructive policy re-evaluation; current manifests control eligibility for new indexing. | Retirement candidates require review; historical bytes are not automatically current accepted evidence. |
| Five explicit Chroma vector spaces | CLIP aligns images/text, CLAP aligns sounds/text, multilingual E5 small handles compact text retrieval. | General-purpose models are not specialist classifiers; no labelled comparison proves optimality. |
| Segment identities and policy fingerprints | Verify exact part coverage and compatibility before reuse; recover partial publication. | Equal dimensions or matching counts do not establish compatibility. |
| CPU, bounded batches, sequential encoder processes | Operate on the authors' Windows hardware without CUDA. | Latency depends on length, cache and RAM. |
| Independent query snapshot | Chroma already persists vectors on disk. We additionally copy/hash-verify the database for queries to protect the audited original from client migrations/internal writes. This is a project preservation policy, not a persistence requirement. | Extra database disk space; stop writers and refresh to a new directory after data changes. Source media are not copied and embeddings are not recomputed. Coordinated single-index access is an alternative. |
| Asset grouping, diversity quotas, RRF | Avoid long-file dominance, expose modalities and combine rankings without mixing cosine scales. | Quotas alter raw order; similarity and RRF are not species probabilities. |
| Local Qwen 2.5 3B Q4_K_M RAG with E5/CLIP and optional BLIP | Generate from bounded retrieved text, fixed revision/hash, on CPU. | Qwen receives text rather than pixels; captioning, retrieval and interpretation can fail. |
| Restricted evidence IDs and post-generation validation | Resolve literal quotations server-side and distinguish answer, partial answer, abstention and error. | Literal quotations do not prove semantic entailment or species identity. |
| Sequential orchestration, locks, timeouts, atomic reports | Make failures observable and retries safe at each boundary. | Recovery verifies state across stores; there is no global all-or-nothing transaction. |
| One requirements file and layered CI | One dependency contract; offline Windows/Linux checks and separate storage integration. | Native acceptance needs cached weights/RAM outside ordinary CI; verify the submitted commit remotely. |

## Interpreting evidence

Quality manifests carry source keys, status, reason, metrics and policy information. HTML, CSV, JSON and plots make decisions reviewable. Provenance completeness measures populated fields, not independent verification of truth or licences. Distribution comparisons reveal changes caused by filtering; unchanged distributions do not establish absence of bias.

The RAG timeout correction is general: incomplete output remains a technical error, context and evidence are bounded, and multipart questions have distinct evidence slots. No answer is hard-coded for the frog example. See [Task 3](generative_tasks_documentation.md) and [validation](testing_and_validation.md).

## Initial orchestrator package

The supplied ZIP had SHA-256 43f9579a7fbc747a49bb94c1eb89bcd9b88b34c57e44d62314db4b73674bf141. Its five additive entries were the orchestration package, its test file, its guide and a patch README. It did not replace validators, indexers or data. Its 47 offline tests were an initial baseline; current recovery, preservation and native-model evidence are documented separately.
