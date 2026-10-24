# EcoSentinel — 15-minute presentation script

Mario Rodrigo, Sambhav and Wassim

The presentation and spoken script are in English. This is a 15-minute talk, excluding questions and a live demonstration. The timing is a rehearsal target, not a guarantee: delivery speed varies. The script contains about 1,800 words. Allow brief pauses and include the handoffs in each five-minute block. Do not wait for live CPU generation during the timed talk.

## Running order

| Slides | Speaker | Time | Focus |
|---|---|---|---|
| 1–5 | Mario | 00:00–05:00 | Purpose, corpus and data backbone |
| 6–10 | Sambhav | 05:00–10:00 | Quality, encoders and retrieval |
| 11–15 | Wassim | 10:00–15:00 | RAG, operations, validation and conclusion |

## Rehearsal

Read the quoted speech only. Section labels and cues are for rehearsal. Pause briefly after the opening question and the large figures. Look at the audience between complete thoughts. Practise once individually, then once as a group with a timer. Aim for the handoffs at 05:00 and 10:00. Keep technical names steady: C-L-I-P, C-L-A-P, E-five, R-A-G, and Qwen ("kwen"). The speaker allocation is a proposal and can be swapped.

## 1. EcoSentinel

**Mario · 0:00–0:30 · 30 seconds**

Cue: The problem.

A photograph, a field recording and a species description may all refer to the same animal, yet they usually live in separate catalogues. EcoSentinel connects those materials and keeps their sources accessible. We are Mario Rodrigo, Sambhav and Wassim. Today we will explain how we built the system, why we made these choices, and what our validation actually demonstrates.

## 2. One wildlife question, several sources

**Mario · 0:30–1:30 · 60 seconds**

Cue: The person using the system.

Imagine someone preparing an educational activity about Iberian wildlife. They have a photograph and want to find related material, listen to recordings and understand the animal's habitat. Usually, that means moving between catalogues, repeating searches and checking where each piece of information came from. Our proposal brings that journey into one tool. It could support education or help someone explore a biodiversity collection before specialist review. The intended value is easier discovery, with a traceable path back to the original evidence. These are potential benefits of the prototype. We have not measured time savings or tested adoption in an organisation. That distinction runs through the project: we show what the system does, and we keep the remaining evaluation visible.

## 3. The reference corpus

**Mario · 1:30–2:25 · 55 seconds**

Cue: Three modalities and ten species.

We chose ten species of Iberian wildlife to give the project a clear scope. Our reference corpus contains one hundred images from Wikimedia Commons, thirty-four recordings from Xeno-canto, and sixty-four texts from Wikipedia and GBIF. Together, these are one hundred and ninety-eight accepted assets. Images are balanced across species, but the other modalities depend on source availability. For example, we have no audio for the ocellated lizard. That matters because availability affects what a search can retrieve. We retain source identifiers, attribution and available licence information alongside the files. These numbers describe the collection we audited. A new download may produce different material, so its counts and quality need a separate evaluation.

## 4. Four zones, four contracts

**Mario · 2:25–3:45 · 80 seconds**

Cue: Separate responsibilities.

The architecture separates four responsibilities. Landing receives and preserves originals. Formatted converts each modality into a common representation. Trusted checks quality and provenance against explicit policies. Exploitation prepares the representations used by retrieval. This separation gives us a practical recovery path. If we change an encoder, we can start again from Trusted. If a quality rule changes, we can revisit Formatted without downloading the source again. Landing, Formatted and Trusted use S3-compatible object storage deployed in Docker. Object storage fits photographs, recordings and documents with different formats and sizes. Chroma then stores vectors and references to those assets. The Python packages follow the same boundaries, so each stage can run and be tested independently. Internet acquisition is optional. Once the files and model weights are prepared, the pipeline can operate locally. Model-specific choices stay downstream, while the original evidence remains available for inspection.

## 5. Preserving originals, standardising formats

**Mario · 3:45–5:00 · 75 seconds**

Cue: An explainable transformation.

Before ingestion, a Security Gate checks allowed formats, file signatures and input limits. Landing then separates temporary reception from persistent original storage. Promotion uses content identities and verifies the copy before recording completion. In Formatted, each modality has its own converter. Images become RGB JPEG, audio becomes FLAC PCM16, and text becomes UTF-8 with consistent character normalisation and line endings. These choices have trade-offs. JPEG is lossy, and PCM16 can reduce the precision of a higher-depth source. We therefore retain the original file upstream. At this stage, we also preserve audio sample rates and channels. Resampling and segmentation belong in Exploitation, where the model requirements are known. Each transformation retains source keys and hashes, so a result can be traced back to its original bytes. With that foundation in place, Sambhav will explain how we assess quality and build retrieval.

## 6. Trusted retains potentially useful signals

**Sambhav · 5:00–6:00 · 60 seconds**

Cue: Technical quality and ecological context.

In Trusted, we distinguish a technically invalid file from a signal that deserves review. A quiet recording might contain a useful call. A dark photograph might be the observation someone needs. We therefore avoid aggressive cleaning, automatic denoising and visual correction. We use YAML policies, independent validators and duplicate checks. Reports record accepted assets and quality warnings. In the reference corpus, thirty-two images have possible watermark flags, and nine recordings have low-energy warnings. These are heuristic signals, not confirmed defects. All one hundred and ninety-eight assets pass the technical rules for this collection. Passing those rules does not establish correct biological labels. Semantic review remains a separate responsibility, and the reports preserve enough detail to support it.

## 7. 198 assets, 6,021 embeddings

**Sambhav · 6:00–7:10 · 70 seconds**

Cue: Segments explain the difference.

In Exploitation, one asset can produce several vectors. A photograph has a visual representation, while a long recording is divided into windows and a long document into passages. That is how one hundred and ninety-eight assets produce six thousand and twenty-one embeddings. We maintain five collections: three for individual modalities and two shared spaces. The image-and-text collection places aligned representations together. The audio-and-text collection does the same for sounds and language. Each record includes its asset identity, segment position, content hash and model-policy contract. This tells us what a vector represents and helps detect incomplete publication. Before computing embeddings again, we check both compatibility and exact segment coverage. A matching record count alone is insufficient: two duplicated parts could hide a missing part. Compatible reruns reuse the existing index instead of repeating inference.

## 8. The encoder follows the relationship

**Sambhav · 7:10–8:10 · 60 seconds**

Cue: CLIP, CLAP and E5.

We do not use one encoder for every relationship. CLIP connects visual concepts with images and aligned text. CLAP connects audio with language, which lets a description retrieve relevant recordings. For text, we use multilingual E5 small, which gives us a compact representation for queries in several languages. These are practical choices for CPU execution and reuse of pretrained models. We have not established that they are the best wildlife models through a labelled comparison. Their limitations matter. English sound descriptions may work better with CLAP, and CLIP is not a specialist species classifier. Equal vector dimensions do not make two embedding spaces compatible. We keep separate contracts and compare similarity within the appropriate space, rather than mixing unrelated distances.

## 9. Task 1: similarity within a modality

**Sambhav · 8:10–9:10 · 60 seconds**

Cue: One reference, the same type of result.

Task one answers a focused question: given an asset, which other assets of the same type resemble it? An image retrieves images, a recording retrieves recordings, and text retrieves text. The query can start from an indexed record or an external file. When we use a stored asset, we exclude all of its segments, so the system cannot return the reference as its own best match. We also group retrieved segments by asset. Otherwise, several windows from one recording could occupy the result list. The interface exposes results and provenance. The order reflects model similarity, rather than a species probability. An external file acts only as a query. Uploading it does not automatically add it to the dataset or the vector index.

## 10. Task 2: retrieval across modalities

**Sambhav · 9:10–10:00 · 50 seconds**

Cue: Shared spaces and rank fusion.

Task two extends that journey across modalities. A description can retrieve images and text in the shared CLIP space, or recordings and text through CLAP. The screenshot shows the actual interface for a combined search. We also offer a view across all modalities. Here we combine ranking positions using Reciprocal Rank Fusion, rather than comparing raw scores from different encoders. An explicit diversity policy gives available modalities a place in the results. The combined order therefore follows a documented policy, rather than a single global distance. With retrieval available, Wassim will explain how we use its evidence to generate an answer.

## 11. Task 3: evidence before generation

**Wassim · 10:00–11:15 · 75 seconds**

Cue: The RAG path.

Task three uses retrieval-augmented generation. We first retrieve evidence from the corpus, then ask Qwen to answer using that context. If a query includes an image, CLIP provides visual matches and BLIP produces an automatic description. Qwen receives that text and retrieved passages. It does not inspect the image pixels directly. We use Qwen two point five, with three billion parameters, in a quantised GGUF format, to make CPU generation practical on our machine. The model revision and file hash are fixed. We limit the context and control model loading. The generator selects permitted evidence identifiers, and the server resolves their quotations. We then check that references and extracts belong to the retrieved sources. Missing support produces abstention or a partial answer. A generation failure produces a technical error. These states remain distinct, and the user can inspect how the response was built.

## 12. An answer with sources you can inspect

**Wassim · 11:15–12:15 · 60 seconds**

Cue: The real frog example.

This example comes from a real test using a frog image already in Trusted. We asked about habitat and diet for the retrieved candidates, without confirming the species in the photograph. The interface presented a corpus candidate and two claims with source extracts. Opening a reference lets us compare the answer with the retrieved document. The case also exposed an earlier technical failure: generation reached its time limit and left incomplete JSON. We reduced context and retrieved by aspect, keeping separate evidence for habitat and diet. Regression tests now cover those failure boundaries. This test used the real models, but it remains one example. An existing quotation does not guarantee every interpretation is correct, and visual similarity does not establish a taxonomic identification.

## 13. The second run matters too

**Wassim · 12:15–13:10 · 55 seconds**

Cue: Recovery and compatible reuse.

The system has a sequential orchestrator with sixteen steps. It runs the zones, writes a log for each step and finishes with reconciliation. A resource lock prevents concurrent pipeline runs. When a step fails, execution stops and preserves its report, so we can fix the cause and retry. We do not assume one transaction across all stores. Recovery checks the state at each boundary. We tested this with two complete runs using isolated storage and real CPU models. The first produced three synthetic assets and seven vectors. The second completed with zero new vectors across all five collections. This demonstrates integration and idempotent reuse. The synthetic noise image and audio tone do not evaluate wildlife retrieval quality.

## 14. What we validated

**Wassim · 13:10–14:10 · 60 seconds**

Cue: Different levels of realism.

Our validation has several layers because they reveal different problems. Three hundred and forty-four offline tests cover contracts, edge cases and controlled failures. One additional integration test runs all zones with real S3 storage and Chroma, using deterministic encoders. Separately, we ran the full CLI and generative examples with real CPU models. Combined statement coverage is seventy-one point two five percent. That measures executed code, not retrieval accuracy. We also verified that the original six thousand and twenty-one embeddings retain identical files and hashes, and that the MinIO inventory remains unchanged. GitHub Actions configures checks on Windows and Linux. Its remote result must be checked for the submitted commit. A labelled evaluation set is still needed to measure retrieval relevance and semantic answer quality systematically.

## 15. A query with a traceable path

**Wassim · 14:10–15:00 · 50 seconds**

Cue: The project contribution.

Let us return to the person who started with a photograph. They can now explore related assets, move across modalities and ask a question linked to its sources. That experience rests on preserved originals, explicit transformations, quality policies and model contracts. This is EcoSentinel's contribution: connecting a useful query workflow with a data backbone we can explain and check. The repository includes a user guide, design decisions and selected validation evidence. The next evaluation would use labelled examples and specialist review before considering operational deployment. That is the scope of our prototype and the evidence behind it. Thank you. We are ready to discuss the system or show the workflow in the interface.

## Before presenting

Open the PPTX in the actual classroom software and check the projector once. The PDF is the fixed-layout fallback. Speaker notes contain the complete script and project-source references. The reference UI screenshot is in Spanish because that is the implemented interface. Slide 12 explicitly translates the observed source fragments into English.

The remote CI result is recorded as pending in the reviewed evidence. If you verify a green run before the defence, update that statement and the evidence together. Do not describe coverage as model accuracy. A visual corpus candidate does not confirm the species of an external photograph.
