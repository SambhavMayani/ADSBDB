# Instructions

**Repository:** https://github.com/SambhavMayani/ADSBDB<br/>**Authors:** Mario Rodrigo, Sambhav and Wassim. **Requirements:** 64-bit Python 3.11, Git Bash on Windows, Docker Desktop. Grant the supervisor access to a private repository.

## 1. Install and verify the code

```bash
git clone https://github.com/SambhavMayani/ADSBDB.git
cd ADSBDB
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m orchestration.pipeline --plan
```

Expected: offline tests pass; a 16-step plan needs no data/models. Installation needs Internet. Linux activation/CPU wheel instructions: README.md.

## 2. Prepare models before the first pipeline run

A **dataset** is the image/audio/text collection. Libraries provide code; **model weights** are pretrained parameters downloaded separately. Preparation neither trains models nor creates dataset embeddings. The pipeline loads cached weights offline; --with-acquisition does not download models. Git excludes data, weights and credentials.

```bash
python -m exploitation_zone.prepare_models --download
python -m multimodal_tasks.rag_model --download
HF_HUB_OFFLINE=0 python -c "from huggingface_hub import snapshot_download; \
from multimodal_tasks.generate import MODEL, REVISION; \
snapshot_download(repo_id=MODEL, revision=REVISION, token=False)"
```

Prepare once online; reuse caches. Expect "Embedding models ready". Qwen and BLIP are Task 3 prerequisites only. Exact reference evaluation requires the authors' matching data/storage/index, absent from Git.

## 3. Start storage and select one dataset route

```bash
cp -n .env.example .env
# Set local storage credentials in .env before starting Docker.
docker compose up -d
python orchestration/check_minio_connection.py
```

**A. No local raw files:** configure provider credentials, including XENO_CANTO_API_KEY in .env, then download through the three acquisition scripts and continue the pipeline:

```bash
python -m orchestration.pipeline --run --with-acquisition
```

**B. Raw files already local:** keep _metadata.json sidecars under data/raw_dataset/&lt;modality&gt;/&lt;species_id&gt;/ and skip acquisition:

```bash
python -m orchestration.pipeline --run
```

**C. Matching S3/Chroma already prepared:** skip A/B; run python -m orchestration.reconcile. Expect completed and no problems. The unchanged reference has 198 accepted assets / 6,021 vectors. Downloads may differ or fail on quotas; inspect logs. Full prerequisites/recovery: docs/user_guide.md.

## 4. Create the query copy once, then start the interface

```bash
python -m orchestration.audit --source data/chromadb --snapshot data/search_index
python -m webapp.server
```

With writers stopped, copy to a new destination. This verifies/copies the existing database, without recomputing embeddings or copying media. The web protects data/chromadb/ from Chroma internal writes by opening this copy: our safety policy, not a persistence requirement. It costs disk and is not synchronised. Reuse if unchanged; after updates create a new path and use --index NEW_PATH.

## 5. Inspect results and exercise the Tasks

The pipeline does not start the web. Open **http://127.0.0.1:8765** after starting it. Try same-modality search, mixed image/text retrieval and a RAG habitat/diet question; inspect citations. Reports: reports/trusted_quality/&lt;modality&gt;/&lt;date&gt;/ (HTML, PNG, CSV, JSON); pipeline logs/JSON: reports/orchestration/. Qwen needs 2.5 GiB available RAM; CPU requests can take minutes. Ctrl+C stops the web. Detailed routes, checks and troubleshooting: **docs/user_guide.md**.


---


EcoSentinel

Multimodal wildlife data management
and evidence based retrieval

ADSDB P1<br/>Universitat Politècnica de Catalunya

**Mario Rodrigo**<br/>**Sambhav**<br/>**Wassim**

25 October 2026

## Project overview

We built a local pipeline that makes heterogeneous wildlife material searchable and auditable. Images, recordings and text pass through separate ingestion, formatting, quality and vector-indexing stages. A single interface supports related-asset discovery, cross-modal exploration and questions answered from retrieved evidence.

Our engineering priorities are reproducibility, explicit contracts, incremental execution and recoverable failures. The reference dataset contains 198 accepted assets and 6,021 persisted embeddings. We preserve original media and distinguish technical data quality, retrieval relevance and biological correctness.

This report explains the domain, the value of the system, the reasons for each zone and model, the three analytical Tasks and the operations environment. It records observed validation and limitations rather than treating plausible model output as verified identification.

Context and data  2   |   Data management backbone  3–6<br/>Similarity methods  7   |   Tasks and interface  8–9<br/>Operations and validation  10


---


# Context and Data

## Domain and purpose

Wildlife information is fragmented across photographs, field recordings and species descriptions. A researcher who finds a relevant photograph may still have to search another catalogue for vocalisations and another source for habitat information. We chose Iberian fauna to make that cross-modal discovery useful within a clearly bounded domain.

EcoSentinel is a prototype evidence workspace for conservation educators, field-study teams and biodiversity analysts. A user can start from an image, recording or phrase, inspect related assets and ask a question grounded in the collection. The potential value is less manual catalogue switching and a traceable route from an answer to its underlying evidence. These are proposed benefits; we have not measured business adoption or time savings.

## Sources and dataset

| Modality | Reference assets | Source and acquisition |
| --- | --- | --- |
| Images | 100 | Wikimedia Commons API; ten images per species |
| Audio | 34 | Xeno-canto API; recordings available for nine species |
| Text | 64 | 20 Wikipedia articles and 44 GBIF description records |

The ten species include Iberian lynx, wolf, deer, wild boar, eagle, eagle owl, kingfisher, robin, Perez's frog and ocellated lizard. Scientific identifiers in config/species.yaml keep the zones consistent. We deliberately include audio as a third modality: it adds ecological context and requires distinct decoding, quality metrics and an aligned audio-text encoder.

Acquisition scripts save source URLs, provider identifiers, hashes and available attribution/licence fields beside the raw files. Wikipedia records also retain revision information. Downloads are optional; saved raw data can enter the same pipeline offline. We store provider labels as provenance, not expert-verified species annotations.

## Representativeness and responsible reuse

The sample is small and curated. Images are balanced by design, but text coverage ranges from two to twelve documents per species; audio is absent for the lizard and limited to two lynx recordings. Source availability therefore influences retrieval. A technically valid record is not automatically a representative ecological observation.

Raw assets and weights are not bundled in Git. Existing metadata includes different reuse terms, including non-commercial audio licences. Attribution must travel with a dataset handoff. The academic prototype does not establish commercial redistribution rights; a production application would need an asset-by-asset permissions review and expert validation.

Source metadata and model references: docs/data_sources.md. Aggregate dataset evidence: docs/evidence/quality_*.json. The recorded counts refer to the audited reference installation, not a promise about later API downloads.


---


# The Data Management Backbone

## Independent zones with explicit responsibilities

We separate reusable data management from model-specific preparation. Python packages match the four zones; Landing, Formatted and Trusted use separate S3 buckets, while Exploitation uses embedded Chroma. The Docker service is the pinned SILO S3-compatible distribution. Using S3 object storage fits heterogeneous media without forcing binary payloads into relational rows; Chroma then provides vector-oriented retrieval without another server.

[Architecture diagram: Landing → Formatted → Trusted → Exploitation → Tasks and local interface]

## Landing preserves evidence

Optional source adapters first create raw files and metadata sidecars. Before ingestion, a Security Gate checks extensions, signatures, filename/size limits, image structure and archive expansion limits. It is a processing safeguard, not a malware scanner. Temporal Landing receives accepted inputs; Persistent Landing organises originals by modality and species with traceable naming and ingestion metadata.

Content identities and completion markers prevent duplicate promotion. Copy verification checks provenance, size and SHA-256 before completion. We retain Temporal objects by default; an explicit cleanup option is available only after verifying the persistent copy. Retention costs space but makes recovery safer. A failed copy or incomplete marker cannot be interpreted as a completed asset.

## Formatted standardises syntax

| Type | Canonical representation | Why and trade-off |
| --- | --- | --- |
| Image | JPEG RGB | Wide decoder support and manageable storage; JPEG is lossy, so the original remains in Persistent. |
| Audio | FLAC PCM16 | Portable lossless compression of the selected PCM representation; original higher precision is retained upstream. |
| Text | UTF-8, NFC and LF | Consistent decoding and paragraph handling across HTML, JSON, documents and plain text. |

One converter per modality makes failures and tests independent. The stage avoids model-specific cropping, tokenisation or resampling. Audio keeps its source rate/channels when converted; segmentation and 48 kHz mono preparation belong downstream. Unsupported or unextractable content produces an explicit failure instead of a fabricated empty record.

Separate objects cost storage, but preserve a reversible lineage from each derived asset to its original. Configuration and checksums record the transformation boundary; a distributed transaction across all stores is not assumed.


---


# Trusted Zone and Quality Analysis

Trusted evaluates generic usability and lineage before any particular model is selected. YAML policies keep thresholds visible and versioned. Each modality has its own validator and measurements, with shared publication utilities. Accepted objects and JSON quality manifests feed reproducible HTML, CSV and plot reports.

## Conservative decisions preserve ecological signal

Images must decode and satisfy technical dimensions and provenance. Exact hashes and pHash candidates followed by SSIM/colour confirmation detect duplicates. Darkness, low sharpness, monochrome appearance and possible watermarks are primarily review signals. Audio checks integrity, duration, amplitude statistics and exact PCM duplicates; it does not denoise, trim silence, normalise loudness or discard distant calls. Text preserves language and content, with strict decoding, exact duplicate checks, near-duplicate warnings and privacy-pattern counts.

These choices protect future analytical uses. A quiet interval may be ecologically meaningful; a short GBIF description need not resemble a full article. We reject technical failures and qualifying duplicates, distinguish operational errors from quality rejection, and retain previously accepted bytes when a later evaluation suggests retirement. Reconciliation exposes obsolete index references instead of deleting them silently.

## Observed reference quality

[Figure: asset counts by species from versioned reference quality summaries]

| Modality | Observed quality indicators | Interpretation |
| --- | --- | --- |
| Images | 100/100 accepted; 14 monochrome-like, 32 possible-watermark flags | Flags may overlap; they are not verified defects. |
| Audio | 34/34 accepted; 2 low-RMS and 9 low-energy flags; median 40.91 s | Quiet recordings retained; longest recording 752.37 s. |
| Text | 64/64 accepted; median 208.5 words; range 33–13,869 | Different source lengths motivate later segmentation. |

The 19 October reference reports record 100% provenance-field coverage and no removals for this curated batch. This means the measured fields were populated, not that all content was correct. Before/after species distributions are unchanged; the lack of lizard audio remains visible. Synthetic pipeline reports are kept separate from these dataset observations.

Limitations are explicit: watermark and near-duplicate heuristics have no labelled precision/recall benchmark; text near-duplicate comparison is quadratic at the current small scale. Future expansion needs indexed duplicate candidates and annotated evaluation. Evidence: docs/evidence/quality_images.json, quality_audio.json and quality_text.json.


---


# Trusted Reports, Metrics and Interpretation

## From per-asset decisions to reviewable reports

Each evaluated asset has audit JSON under trusted-zone/_quality/&lt;modality&gt;/, recording source identity, policy, status/reason, measurements and duplicate/warning information. Generators aggregate the currently stored manifests without decoding media again, changing decisions or running encoders. Their scope includes existing assets, not just new inputs from that run.

| Output | Purpose |
| --- | --- |
| quality_report.html | Human-readable quality overview with tables and linked plots. |
| summary.json | Machine-readable aggregate counts, provenance, flags and modality-specific statistics. |
| metrics.csv | One flattened row per evaluated asset, for inspection and independent analysis. |
| PNG figures | Portable histogram and before/after bar-chart images linked from the HTML. |

Output: **reports/trusted_quality/&lt;modality&gt;/&lt;timestamp&gt;/**. Open the HTML with its PNGs alongside it. A compatible rerun creates a new report without republishing identical assets. Runtime reports remain outside Git; selected reference summaries are versioned.

## Measurements are chosen for each modality

| Modality | Recorded measurements and plots | Purpose and interpretation |
| --- | --- | --- |
| Image | Megapixels, file MB, brightness (0-255), aspect ratio and Laplacian sharpness; duplicate, monochrome and possible-watermark indicators. | Profile decoding/usability and review signals. Sharpness and watermark heuristics do not establish biological validity. |
| Audio | Duration (s), RMS/peak (dBFS), clipping (% samples), low-energy (% 50-ms windows), sample rate (Hz), channels and exact-PCM duplicates. | Expose recording variability and clipping/quietness without trimming, denoising or changing accepted audio. |
| Text | Words, characters, bytes, unique-token ratio (TTR), alphanumeric fraction, duplicate candidates and possible email/IPv4 counts. | Describe document length/structure and review privacy patterns. Counts retain no matched private values; TTR depends on length. |

## Plots show distributions and the effects of the policy

Histograms profile the configured numeric features; bar charts compare evaluated versus accepted counts by species and data source. Audio/text summaries include count, mean, median, minimum, maximum and p10/p90 for available measurements. Image summaries also report retention, provenance coverage, warning counts, measured processing costs and Jensen-Shannon distribution shift in bits.

Before/after bars describe selection, not automatic changes to media. All 100 reference images remain accepted, with species shift of 0.0 bits: matching bars do not imply missing controls. Provenance coverage measures field presence, not truth. The 32 possible-watermark and nine low-energy flags remain warnings rather than automatic rejection.

Generators: trusted_zone/reporting/generate_image_report.py and generate_modality_report.py. Reference evidence: docs/evidence/quality_images.json, quality_audio.json and quality_text.json. Thresholds and reproduction commands: docs/trusted_zone_documentation.md.


---


# Exploitation Zone and Model Choices

Vectors retain asset/segment IDs, source keys, hashes and policy fingerprints; S3 retains the media. Three single-modality and two shared collections implement retrieval. Equal dimensions never establish compatibility between models.

| Collection | Encoder and dimension | Vectors |
| --- | --- | --- |
| Images | CLIP ViT-B/32, 512 | 100 |
| Audio | CLAP HTSAT unfused, 512 | 357 |
| Text | Multilingual E5 small, 384 | 547 |
| Image and text | CLIP image + aligned multilingual text, 512 | 1,763 |
| Audio and text | CLAP audio/text towers, 512 | 3,254 |

## Why these pretrained encoders

**CLIP** supplies a common image/text representation, enabling semantic visual discovery without training on our small dataset. The multilingual text adapter is aligned to CLIP ViT-B/32, so Spanish/English queries can share the image space. Its captions-oriented representation is useful for visual concepts but less suited to detailed biological prose.

**E5 small** provides multilingual passage retrieval with a smaller CPU footprint than larger alternatives. We use the prescribed query and passage prefixes and 384-dimensional normalised vectors. A dedicated text encoder complements CLIP for habitat and behavioural descriptions. **CLAP** adds genuine audio/text alignment; a speech recogniser would lose non-verbal animal sounds. The unfused model is used with 10-second, 48 kHz mono windows. Its language/domain limitations make English acoustic prompts preferable.

## Segmentation and compatible re-execution

Text windows use E5 320/40, multilingual CLIP 96/12 and CLAP 60/8 token window/overlap settings. These respect each configured encoder budget and reduce boundary loss. All tail segments are covered. Overlap and multiple spaces explain why 198 assets produce 6,021 vectors; the vectors are not 6,021 independent observations.

Stable IDs, hashes and exact part coverage allow compatible assets to skip inference. Incompatible collections fail; partial publication can be retried. The immutable manifest resolves historical null revisions without changing v1 fingerprints, but records observed cache commits rather than retrospectively proving every original inference.

Models run sequentially with small CPU batches; audio decoding still scales with duration.

## Persistent index and independent query copy

Vectors persist in data/chromadb/ and survive restarts. We copy/hash-verify this database into data/search_index/ because Chroma may perform internal writes on opening. Search rejects the original path. This preservation policy is additional to persistence: copying performs no encoder inference and does not duplicate source media. It costs disk and freshness management. Stop writers and create a new copy after updates; --index selects it. A coordinated single-index service is an alternative.

Revisions: config/model_manifest.json. Encoder policies: config/exploitation.yaml. Model cards: docs/data_sources.md.


---


# Similarity Search and Compatible Spaces

## Cosine measures the proximity of two representations

For non-zero vectors, **cos(q,x) = dot(q,x) / (||q|| * ||x||)**. Our encoders normalise vectors to unit length, so scoring becomes a dot product. Cosine ranges from -1 to 1: higher values mean closer directions in that compatible representation. A value of zero means perpendicular directions. It is neither a species probability nor a universal relevance threshold.

| Candidate x for q=(1,0) | Cosine | Illustrative interpretation |
| --- | --- | --- |
| (0.96, 0.28) | 0.96 | Most aligned of these three candidates |
| (0.60, 0.80) | 0.60 | Less aligned with this query |
| (0.00, 1.00) | 0.00 | Perpendicular to the query |

The calculation above is two-dimensional for clarity; production vectors have 384 or 512 components. Recorded examples score 0.912 for image-to-image retrieval and 0.332 for a text-to-image candidate. Those query types have different score distributions; these observations do not establish good/bad bands or identification accuracy.

## HNSW finds neighbours among many stored vectors

Chroma is configured with **Hierarchical Navigable Small World** and cosine distance. HNSW is approximate nearest-neighbour search: sparse upper graph layers allow longer hops, then denser lower layers refine candidates. It can miss a true nearest neighbour. We use Chroma's implementation, without claiming a measured speedup or recall on wildlife queries.

For at most **64 eligible vectors after filtering**, our code instead compares every vector exactly, with cost O(N*d). This bounded path handles tiny/new collections without requiring a materialised HNSW disk segment. Larger queries delegate to Chroma and expose cosine as 1 minus distance. The candidate pool grows when necessary to retrieve enough distinct assets.

## Different modalities require aligned encoders

Image/text CLIP and audio/text CLAP can compare different file types within their respective aligned spaces. CLIP and CLAP both have 512 dimensions, but their coordinates are unrelated: a cross-model dot product is mathematically possible and semantically invalid. Different dimensions fail validation. Routing selects compatible encoders/collections and checks model-policy contracts; dimension alone cannot reveal the origin of an arbitrary vector.

Collections are containers, not necessarily different coordinate systems. Compatible visual CLIP vectors can serve both image and image-text collections. Changing the query space resolves the same asset's compatible representation by asset_id; absence produces an explicit error.

## Federation combines positions rather than coordinates

A federated query is embedded separately by E5, CLIP and CLAP. **Reciprocal Rank Fusion** sums 1/(60+rank), once per asset per list. Positions 1 and 3 give 1/61 + 1/63, approximately 0.03227. This is an RRF score, not cosine or confidence. The constant 60 is independent of the requested top-k. Raw vectors and cross-model cosine magnitudes are not combined.

Implementation: multimodal_tasks/search.py, exploitation_zone/encoders.py and vector_store.py. Course: Vector Databases, pp. 31-34 and 87-105. Recorded qualitative scores: docs/presentation/task_examples.json. Detailed limits: docs/multimodal_tasks_documentation.md.


---


# Multi Modal Tasks and User Interface

## Task 1 discovers related assets within a modality

A reference image retrieves images; a recording retrieves recordings; a text query uses E5 for texts. Stored-record queries reuse the existing vector and exclude the entire reference asset, including its other segments. An external query is embedded in memory without ingestion. Results are grouped by asset so a long document or recording does not occupy the ranking solely through repeated chunks.

The metric, exact/approximate search paths and space-compatibility rules are explained on page 7. Tests exercise both the bounded exact path and a larger real Chroma collection. Visually related but taxonomically different animals can rank together; similarity alone does not verify species identity.

## Task 2 connects modalities through aligned spaces

The image-text and audio-text collections each contain both modalities. Text can retrieve photographs and descriptions, or recordings and descriptions. Image/audio inputs can also retrieve mixed results. An explicit diversity policy allocates available results across modalities, making the shared information visible instead of allowing numerous text chunks to dominate.

Federated search uses the RRF method described on page 7. Fusion and modality quotas change the ranking objective: the output is a useful mixed view, not a pure global cosine top-k. Its value should eventually be assessed with relevance labels. A filtered or very small result set may contain only one modality.

## One local interface exposes the complete workflow

| Tab | Task and user workflow |
| --- | --- |
| Explorar por texto | Text-only E5, either shared space, or all modalities; inspect sources and filters. |
| Buscar similares | Upload an image or short recording; choose same-modality or mixed retrieval. |
| Preguntar al corpus · RAG | Ask about the dataset, optionally with an uploaded or stored image; inspect cited claims and diagnostics. |

Result cards expose source lineage and related-asset actions. RAG shows candidate species as hypotheses, links claims to reference excerpts, and distinguishes complete answers, partial answers, abstention and technical errors. The user can inspect the model revision, request ID and runtime without needing a terminal.

The interface's quantity selector requests 1-50 distinct assets, with default 8; CLI users set --limit N. This is a maximum across the result set. RAG keeps its independent evidence budget.

The web server binds to loopback, validates host/origin and upload limits, and serialises CPU work. The static frontend requires no build toolchain. This reduces setup complexity for assessment, but provides no public authentication, multiuser capacity or deployment-grade isolation. A hosted service would need a separate architecture and operational controls.

A concise case table and expected behaviors are in docs/user_guide.md. Automated HTTP tests cover real request/response handling, input rejection, provenance and protected storage boundaries. Native-model acceptance complements those structural tests.


---


# Task 3 Retrieval Augmented Generation

Task 3 automatically retrieves stored evidence before invoking a pretrained generator. We combine BLIP image captioning, CLIP visual similarity and E5 text retrieval with Qwen2.5-3B-Instruct-GGUF in Q4_K_M form. This implements the assignment's generative pipeline requirement and its recommendation to reuse Tasks 1 and 2.

## A bounded multimodal retrieval pipeline

For image input, BLIP produces an unverified description and CLIP retrieves visual candidates. Candidate labels guide text searches by requested aspect, such as habitat or diet; a bounded lexical scan complements E5 and retains distinct passages from the same article. A global query remains available so retrieval is not reduced to a hard species assignment. We avoid injecting a noisy caption verbatim into every biological search.

Rank fusion selects references, then an evidence selector packs at most eight literal units and 1,600 characters for generation. Full reference excerpts remain available in the interface. The prompt treats retrieved material as data, preserves uncertainty about the uploaded animal and asks for concise claims backed by allowed evidence IDs.

## Why Qwen and BLIP

A 3B quantised instruction model makes local CPU execution practical without a paid API or a GPU requirement. The pinned GGUF is verified by SHA-256; llama.cpp generates under a JSON grammar. BLIP provides a separate, auditable image-to-text stage. We accepted the information loss of this adapter to control memory and keep retrieval and generation independently testable. Qwen receives text, **not image pixels**; this is not a native visual question-answering model like the assignment's LLaVA example.

Multi-aspect requests use constrained slots for up to two claims. An unsupported aspect can return null and becomes an explicit partial answer. Post-validation checks structure, allowed source IDs, exact quote membership, length and obvious incomplete clauses. It does not prove semantic entailment. Domain and aspect planning use vocabulary heuristics and can miss unfamiliar phrasing.

## Failure states and observed behavior

An evidence-based abstention differs from invalid JSON, a token limit or a generation timeout. Technical failures keep references/candidates visible. Generation is limited to 320 output tokens and 120 seconds, with four CPU threads and a 2.5 GiB available-memory check. All configured revisions, policy hashes and stage timings are auditable; uploads are not added to the dataset.

Native acceptance recorded five CLI cases: text habitat, stored-image habitat, conditional frog identification, unsupported genome and an unrelated query. A separate browser run answered both frog habitat and diet with verified excerpts in 131.8 seconds total (76.1 seconds generation). One lynx response was less directly relevant. These checks demonstrate execution and failure handling, not broad species-identification accuracy.

The reference model card identifies the Qwen Research licence; deployment beyond academic assessment needs review of its terms. BLIP uses the model card linked below. Native outputs and preservation summaries are recorded in docs/evidence/native_models.json.

Qwen GGUF: <link href="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF" color="#24546A">https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF</link>

BLIP captioning: <link href="https://huggingface.co/Salesforce/blip-image-captioning-base" color="#24546A">https://huggingface.co/Salesforce/blip-image-captioning-base</link>


---


# Operations and Validation

## From independent scripts to a recoverable pipeline

One orchestrator runs 16 sequential steps: storage, ingestion/promotion, three formatters, three validators, five index stages and reconciliation. Acquisition adds three. Subprocesses use the active Python interpreter without a shell. A local OS lock prevents overlapping orchestrator runs in this checkout, but does not coordinate manual writers or other machines.

Each stage has a timeout, UTF-8 logs and an atomic JSON report. Failures stop later steps; interrupted children terminate. Restarting rechecks persisted asset/vector state. Shared S3 clients have bounded retries. Credentials remain local and configured secrets are redacted from logs.

## Evidence at different levels

| Level | Observed result and scope |
| --- | --- |
| Static quality | Ruff checks and one formatting standard across application code and tests; one pinned requirements file. |
| Offline suite | 364 passing tests; 64.40% offline statement coverage. With the isolated integration test, combined coverage is 71.82%; this is not model accuracy. |
| Storage integration | One passing end-to-end test using isolated real S3/Chroma and deterministic encoders; repeat execution checked. |
| CPU acceptance | Full CLI with three synthetic assets and seven vectors; native retrieval and RAG checked separately on the reference dataset. |
| Preservation | Original Chroma file hashes and 6,021 counts checked; S3 keys, sizes and ETags compared. No dataset regeneration. |

Fault-injection tests cover incomplete vectors, invalid policies, decoder/storage failures and preservation of accepted data. Temporary native indexes close on Windows.

## Automatic checks, reproducibility and limits

GitHub Actions is GitHub's automated test service. After a push or pull request, our workflow installs dependencies on fresh Windows/Linux machines, checks style and runs offline tests. A Linux job tests isolated S3 storage. The 60% coverage threshold means tests must execute 60% of measured code statements; it is not model accuracy. Test/coverage reports are saved. Real-model checks remain manual because weights, RAM and timings vary.

Before submission, open the repository's Actions tab and verify a successful run for the submitted commit. Local test success alone does not confirm that remote result.

A clone can run offline tests and the synthetic demonstration. Reproducing the 198-asset reference also requires matching data, metadata and model weights. New downloads may differ. The instructions explain both data routes, the query copy and web startup.

The query copy needs refreshing after data updates. Failures recover per asset, without a transaction across all zones. Pairwise text duplicate checks become expensive as data grows; long recordings need more decoding RAM. No expert-labelled benchmark yet measures retrieval or biological accuracy. Future evaluation should also measure unnecessary abstentions when relevant evidence exists.

Requirement mapping: docs/p1_requirements.md. Full procedures and evidence: docs/user_guide.md, docs/testing_and_validation.md and docs/evidence/.
