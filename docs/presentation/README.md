# EcoSentinel presentation

**English / 24 slides / rehearsal target 15:00; allow approximately 15–17 minutes after practising together.** The spoken script is 1,763 words. It opens with a concrete question about the photograph and concentrates on project decisions and their evidence.

- [Editable PowerPoint](EcoSentinel_presentation.pptx), with full speech and source references in slide notes.
- [Projection PDF](EcoSentinel_presentation.pdf), a fixed-layout backup.
- [Speaker script PDF](speaker_script.pdf), timing overview and one page per slide.
- [Editable script](speaker_script.md), including answers to likely examiner questions.
- [Content source](presentation_content.json), [recorded retrieval examples](task_examples.json) and [quality chart data](quality_charts.json).
- [Pipeline overview](pipeline_overview.png), the architecture diagram from slide 4 exported as an image.

Mario covers slides 1–8 (00:00–05:10), Sambhav 9–18 (05:10–11:15), and Wassim 19–24 (11:15–15:00). Speaker allocation is a proposal. Rehearse together; actual duration depends on pace and pauses. Questions and live CPU inference are outside the timed talk. Titles and cues are rehearsal instructions, not extra spoken paragraphs. The complete pipeline diagram remains on slide 4.

## Decisions and report examples

Slide 5 distinguishes **SHA-256 hashes from embeddings**: byte fingerprints support identity/integrity, while model vectors support similarity. The recompression example is conceptual rather than a new inference measurement.

Slide 6 shows the concrete **Landing** identity: `temporal_landing/<SHA-256[:16]>__<filename>`. Temporal reuse checks source identity. When Temporal is absent, an independent completion record identifies a Persistent target. A compatible marker and existing target permit skipping; no marker means a new ingest; conflicts or broken targets fail. Promotion verifies the copy before writing completion. This record attests Persistent promotion, not Trusted acceptance. Renaming changes technical ingest identity; Trusted applies content deduplication separately.

Slide 7 illustrates all four **Landing name/content combinations** with two existing photographs, abbreviated hashes and illustrative filenames. With compatible source metadata and an existing Temporal object or valid completion record: same bytes + same name skips; same bytes + different name enters; different bytes + same name enters under another key, preserving the first object; changing both enters too. Hashes shown refer to the embedded example bytes, not the original raw-data names. The script makes technical ingestion reuse distinct from Trusted content/perceptual deduplication. SHA-256 is not LSH. A changed file may look unchanged, and a truncated hash prefix is not a mathematical collision-free guarantee.

Slide 8 justifies **Formatted** choices: compact photographic RGB JPEG at quality 95; FLAC PCM16 for compressed PCM; UTF-8/LF/NFC for readable multilingual text. It includes the six real multiframe image sources and primary-frame policy. The speech explains dimensions, format alternatives, JPEG loss, PCM16 quantisation and extraction loss. Complete originals remain in Persistent. Model-specific cropping/resampling belongs in Exploitation; the zone guide retains the detailed transparency/EXIF policies.

Slide 9 explains **Trusted** quality rules and budgets: images 20 decimal MB, 40 MP and minimum 128 by 128; audio 200 MB; text 4 MB. These are operational thresholds. Warnings remain distinct from rejection, and later errors/rejections retain earlier accepted bytes.

Slide 10 shows the actual 19 October 2026 image-quality report. Slides 11 and 12 contain **editable native charts** derived from its recorded data and the corresponding audio report. Images remain at ten per species, with zero observed Jensen–Shannon distribution shift. All 34 recordings remain accepted, including nine with many low-energy windows. Neither metric proves biological correctness or population representativeness.

The audio chart groups existing per-recording measurements into fixed 20-percentage-point bins for legibility. The original HTML uses six data-dependent bins. No per-asset measurement or quality decision was recomputed. The data file records bin boundaries, counts, source CSV hash and image species-label mapping. English chart labels abbreviate golden eagle, Iberian lynx and ocellated lizard; full species IDs remain in the data. PowerPoint embeds chart data snapshots for editing.

## Task examples and validation

Slides 13–14 explain segment coverage, model-policy compatibility and why CLIP, CLAP and multilingual E5 serve different retrieval relationships. Counts alone do not establish complete indexing. Image/text comparisons use aligned CLIP encoders; audio/text comparisons use aligned CLAP encoders. Independent models do not share a comparable coordinate system. Federated retrieval combines their per-model positions using reciprocal rank fusion, not raw cosine scores.

Slide 15 explains cosine as the dot product divided by both vector lengths. The illustrative unit query `(1, 0)` gives scores 0.96, 0.60 and 0.00 against `(0.96, 0.28)`, `(0.60, 0.80)` and `(0, 1)`. This is a transparent two-dimensional calculation; production vectors have 384 or 512 dimensions. Higher scores mean closer alignment within a compatible space, without a universal relevance threshold or species probability.

Slide 16 names the configured search algorithm: **HNSW (Hierarchical Navigable Small World)** in Chroma, with cosine distance. Its editable schematic shows sparse upper layers and refinement at denser lower layers. The diagram is conceptual, not a measured graph traversal. The code uses an exhaustive exact comparison when the eligible set has at most 64 vectors; larger searches delegate to Chroma. Course references in notes: supplied *5 - Vector Databases.pdf*, pages 31–34 (exact nearest-neighbour scan/ANN) and 87–105 (HNSW). HNSW is approximate and may miss a true neighbour. We make no measured recall or speedup claim, and do not implement PQ, LSH or IVF for retrieval. Chroma implements HNSW; EcoSentinel configures and queries it.

Slide 17 shows actual Task 1 matches at ranks 1 and 3, with the full five-asset ranking retained in the JSON. Four catalogue labels are lynx and one is wolf; rank 2 is a cropped variant. Slide 18 shows the exact Task 2 query, overall image hit 5 (cosine 0.332) and text hit 4 (0.778) from eight results under the diversity policy. It states the current interface top-k range 1–50, default 8. The speech contrasts the recorded 0.912 image-to-image match with the 0.332 text-to-image candidate: score distributions depend on query modality. These values do not define universal good/bad bands.

Slides 19–20 explain RAG and the recorded real-model frog UI example. The interface remains in Spanish and the enlarged extracts are English translations. A complete-genome abstention is a separate test.

Slide 21 shows two full isolated CLI runs with real CPU models: three synthetic assets produce seven vectors, then zero new vectors. Slide 22 distinguishes 364 offline tests, one real S3/Chroma integration test using deterministic encoders, the native CPU CLI runs and eight browser checks. It names failure-state assertions, not only successful executions. The browser checks use synthetic service/RAG doubles and actual HTTP handlers, not production storage or model inference.

Slide 23 explains the harmless executable-header fixture, corruption/resource-boundary cases, retained watermark warnings and 71.82% combined statement coverage. Model/retrieval accuracy requires a separate labelled evaluation. Optional examiner questions in the editable script explain marker scope, renamed copies, hashes, index completeness, cosine, HNSW/exact scanning, cross-modal alignment, rank fusion, top-k and coverage.

The pipeline, encoder and RAG diagrams use editable PowerPoint shapes/connectors. Corpus photographs retain attribution/licences in notes and the example JSON. The slide 2 photograph is illustrative, not claimed to be the recorded RAG acceptance image. Original media and vectors were not rebuilt for this presentation.

Open the PPTX in the classroom software before the defence; package/import/layout checks do not establish identical native font rendering. Use the PDF as fallback. Remote CI must be checked for the submitted commit. The examples are qualitative rather than a labelled biological accuracy benchmark.
