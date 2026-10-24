# EcoSentinel presentation script

English / 19 slides / target 19:20, with a margin up to 20 minutes.

Mario: slides 1–6, 00:00–06:30. Sambhav: 7–14, 06:30–13:20. Wassim: 15–19, 13:20–19:20. Speaker allocation is a proposal; measured rehearsal determines actual duration. Questions and live CPU inference are outside the timed talk.

Read the speech paragraphs only. Cues and times are rehearsal aids. Full speech and provenance references also appear in the PowerPoint notes.

## 01 / EcoSentinel

Mario / 00:00–00:30 / 30 seconds

*Cue: The problem*

A photograph, a field recording and a species description may all refer to the same animal, yet they usually live in separate catalogues. EcoSentinel connects those materials and keeps their sources accessible. We are Mario Rodrigo, Sambhav and Wassim. Today we will explain how we built the system, why we made these choices, and what our validation actually demonstrates.

## 02 / A photograph starts the investigation

Mario / 00:30–01:30 / 60 seconds

*Cue: The person using the system*

Imagine someone preparing an educational activity about Iberian wildlife. They have a photograph and want to find related material, listen to recordings and understand the animal's habitat. Usually, that means moving between catalogues, repeating searches and checking where each piece of information came from. Our proposal brings that journey into one tool. It could support education or help someone explore a biodiversity collection before specialist review. The intended value is easier discovery, with a traceable path back to the original evidence. These are potential benefits of the prototype. We have not measured time savings or tested adoption in an organisation. That distinction runs through the project: we show what the system does, and we keep the remaining evaluation visible.

## 03 / Three modalities, one reference corpus

Mario / 01:30–02:35 / 65 seconds

*Cue: Three modalities and ten species*

We chose ten species of Iberian wildlife to give the project a clear scope. Our reference corpus contains one hundred images from Wikimedia Commons, thirty-four recordings from Xeno-canto, and sixty-four texts from Wikipedia and GBIF. Together, these are one hundred and ninety-eight accepted assets. Images are balanced across species, but the other modalities depend on source availability. For example, we have no audio for the ocellated lizard. That matters because availability affects what a search can retrieve. We retain source identifiers, attribution and available licence information alongside the files. These numbers describe the collection we audited. A new download may produce different material, so its counts and quality need a separate evaluation.

## 04 / The EcoSentinel pipeline

Mario / 02:35–03:55 / 80 seconds

*Cue: Separate responsibilities*

This is the complete pipeline. At the top, optional acquisition or existing local files enter through the Security Gate. The main row separates four responsibilities. Landing preserves originals, Formatted standardises their representation, Trusted checks quality and provenance, and Exploitation builds the five vector collections. A sixteen-step orchestrator controls execution, with a resource lock, timeouts and per-step reports. The first three zones use S3-compatible object storage in Docker. Chroma stores the vectors and references. Below it, the diagram shows a separate snapshot for queries. The interface searches that copy, keeping the original index protected. Each boundary carries source keys, hashes and policy information. If an encoder changes, we can work from Trusted rather than downloading everything again. If a step fails, the report identifies the boundary to inspect. This separation gives us both an execution path and a recovery path, with Internet access remaining optional.

## 05 / Landing recognises a completed ingest

Mario / 03:55–05:05 / 70 seconds

*Cue: An explainable transformation*

A useful engineering case is importing the same file twice. Landing builds a technical identity from the content hash and local filename. It records completion only after verifying the Persistent copy. On a compatible rerun, an existing Temporal object or completion marker prevents a redundant upload. In our isolated rerun, all three assets were already completed and Temporal uploads were zero. If the name or bytes change, the identity changes. That case can enter as another asset because Landing preserves acquisition history. Trusted applies content-quality duplicate policies later. The raw hash remains distinct from the converted file's hash, so we can trace a representation back to its original.

## 06 / Formatted: representation by modality

Mario / 05:05–06:30 / 85 seconds

*Cue: Standardise the format; preserve information for later models*

Formatted handles representation before Trusted evaluates quality. Images become RGB JPEG, providing a consistent representation across source colour modes. The encoder setting of ninety-five prioritises visual fidelity while accepting lossy compression. We keep the original width and height. We do not crop or resize them for a particular model here. Transparency is composed over white because JPEG has no alpha channel. EXIF orientation is retained without rotating pixels, and multiframe sources contribute their primary frame. Audio becomes FLAC PCM sixteen, preserving sample rate, channels and duration when conversion permits. Trusted does not trim quiet intervals or normalise volume. Model-specific resampling belongs later, in Exploitation. Text becomes UTF-eight with consistent line endings and Unicode, while retaining language, case and punctuation. We accept explicit tradeoffs: JPEG is lossy, sixteen-bit conversion can quantise finer input, and text extraction removes layout. Landing keeps the complete originals. Sambhav will explain which quality findings should exclude an asset and which should remain visible warnings.

## 07 / Trusted: rejection or warning?

Sambhav / 06:30–07:30 / 60 seconds

*Cue: Technical quality and ecological context*

Trusted separates technical rejection from useful but imperfect data. For images, our operational limits are twenty decimal megabytes, forty megapixels, and at least one hundred and twenty-eight pixels on each side. File size bounds storage and transfer; pixel count better reflects decoding cost. Audio has a two-hundred-megabyte ceiling and text has four. These are project budgets, not scientific cutoffs or guarantees of peak memory. Exact image hashes detect identical bytes. Perceptual hashes propose candidates, then strict SSIM and colour checks confirm matches. Watermarks, dark images and quiet audio remain warnings. Duplicate scope varies by modality. Later errors or rejections preserve previously accepted bytes and record the reason for review.

## 08 / Quality decisions leave an audit trail

Sambhav / 07:30–08:05 / 35 seconds

*Cue: An actual report and the meaning of its metrics*

This is an actual image-quality report. Validators record a decision, its reason, source, policy and measured signals in each asset's manifest. The reporting layer aggregates those records into HTML, CSV, JSON and plots, without re-opening the original images. Acceptance and provenance completeness tell us what entered Trusted and whether its origin is traceable. The following charts show why we also inspect distributions and warnings, rather than interpreting a hundred percent acceptance as proof of perfect data.

## 09 / Did filtering change species representation?

Sambhav / 08:05–08:50 / 45 seconds

*Cue: Before and after, with a defined interpretation*

This chart compares Formatted and Trusted images for every species. Each pair stays at ten, so the reference collection retains all one hundred images. We measure distribution shift with Jensen-Shannon divergence. Here it is zero because the observed species proportions did not change. The reason to collect this metric is to spot filtering that removes disproportionate amounts from particular species or sources. It does not prove that the initial collection was representative, or that its labels are correct. In this run, the chart explains preservation of an already balanced image sample.

## 10 / Quiet intervals remain in the evidence

Sambhav / 08:50–09:35 / 45 seconds

*Cue: A warning can preserve useful ecological context*

The horizontal axis shows the percentage of low-energy windows in each recording. The vertical axis counts recordings. We use the report's existing measurements, grouped into readable twenty-percentage-point intervals. Both series match because all thirty-four recordings were retained. Nine have at least eighty percent of their fifty-millisecond windows below minus fifty dBFS, which triggers a warning. Quiet passages may contain distant calls or environmental context, so Trusted preserves the complete signal and records the observation. This is a digital-energy measure. It does not prove silence, the absence of wildlife, or poor biological value.

## 11 / Five collections, 6,021 embeddings

Sambhav / 09:35–10:40 / 65 seconds

*Cue: Segments explain the difference*

In Exploitation, one asset can produce several vectors. A photograph has a visual representation, while a long recording is divided into windows and a long document into passages. That is how one hundred and ninety-eight assets produce six thousand and twenty-one embeddings. We maintain five collections: three for individual modalities and two shared spaces. The image-and-text collection places aligned representations together. The audio-and-text collection does the same for sounds and language. Each record includes its asset identity, segment position, content hash and model-policy contract. This tells us what a vector represents and helps detect incomplete publication. Before computing embeddings again, we check both compatibility and exact segment coverage. A matching record count alone is insufficient: two duplicated parts could hide a missing part. Compatible reruns reuse the existing index instead of repeating inference.

## 12 / Three encoders, three relationships

Sambhav / 10:40–11:40 / 60 seconds

*Cue: CLIP, CLAP and E5*

We do not use one encoder for every relationship. CLIP connects visual concepts with images and aligned text. CLAP connects audio with language, which lets a description retrieve relevant recordings. For text, we use multilingual E5 small, which gives us a compact representation for queries in several languages. These are practical choices for CPU execution and reuse of pretrained models. We have not established that they are the best wildlife models through a labelled comparison. Their limitations matter. English sound descriptions may work better with CLAP, and CLIP is not a specialist species classifier. Equal vector dimensions do not make two embedding spaces compatible. We keep separate contracts and compare similarity within the appropriate space, rather than mixing unrelated distances.

## 13 / Task 1: a real image query

Sambhav / 11:40–12:40 / 60 seconds

*Cue: Actual image retrieval*

Here is an actual image-to-image query on our corpus. The photograph on the left is the reference. We show selected matches at ranks one and three with recorded cosine scores. The complete response contains five distinct assets and excludes the reference. Four have lynx catalogue labels; the fifth has a wolf label. These are similarity candidates, not species probabilities. All segments of a stored reference are excluded before grouping by asset. Audio-to-audio and text-to-text use the same workflow. The full response remains available so the selected examples can be checked against the actual ranking.

## 14 / Task 2: one query, images and text

Sambhav / 12:40–13:20 / 40 seconds

*Cue: One text query, two result types*

The same models support cross-modality search. For the exact query on this slide, our shared CLIP collection returned eight assets: four images and four texts, through an explicit diversity policy. We show overall image rank five and text rank four. The GBIF excerpt is copied from the actual response. Provenance links let us inspect both. CLAP provides the analogous sound-and-text workflow. The quota exposes available modalities, but changes the raw similarity order. It is part of the retrieval policy, not evidence that every result is relevant.

## 15 / Task 3: answer from retrieved evidence

Wassim / 13:20–14:45 / 85 seconds

*Cue: The RAG path*

A text question enters retrieval directly. An optional image supplies CLIP matches and a BLIP description. Retrieved passages provide the evidence context for Qwen. The generator receives text and does not inspect image pixels directly. We use Qwen two point five, with three billion parameters, in quantised GGUF format for CPU execution. Its revision and file hash are fixed, with context limits to control memory. Qwen selects permitted evidence identifiers while writing its claims. The server resolves those identifiers to quotations and checks them against retrieved sources. The result can be an answer, a partial answer or an abstention. A technical generation failure remains a separate error. Citations provide an inspectable path to evidence, but do not prove every interpretation is biologically correct.

## 16 / The frog case: evidence and uncertainty

Wassim / 14:45–16:00 / 75 seconds

*Cue: The real frog example*

This is our recorded Task three example using a frog image from Trusted. The question asks for habitat and diet of the retrieved candidates, without confirming the species in the photograph. The interface presents a corpus candidate, then separate claims supported by source extracts. The enlarged text on the slide translates the actual Spanish output into English. In a separate negative test, we asked for the complete nucleotide sequence of the Iberian lynx genome. The model abstained because the retrieved evidence did not support that request. These examples show both the useful path and an explicit limit. The frog response used the real models, but it remains one example. Citations allow inspection. They do not prove every interpretation or identify the animal conclusively.

## 17 / The second run adds zero new vectors

Wassim / 16:00–17:10 / 70 seconds

*Cue: Recovery and compatible reuse*

The system has a sequential orchestrator with sixteen steps. It runs the zones, writes a log for each step and finishes with reconciliation. A resource lock prevents concurrent pipeline runs. When a step fails, execution stops and preserves its report, so we can fix the cause and retry. We do not assume one transaction across all stores. Recovery checks the state at each boundary. We tested this with two complete runs using isolated storage and real CPU models. The first produced three synthetic assets and seven vectors. The second completed with zero new vectors across all five collections. This demonstrates integration and idempotent reuse. The synthetic noise image and audio tone do not evaluate wildlife retrieval quality.

## 18 / An input can fail before it reaches storage

Wassim / 17:10–18:30 / 80 seconds

*Cue: The security gate and tested failure cases*

A useful question is what happens when the input is unsafe or broken. Here, a file named lynx dot jpg contains a harmless Windows executable header. The Security Gate blocks it before hashing or upload. We never run an executable for this demonstration. Separate tests cover misleading extensions, corrupt images, empty files, archive expansion and resource limits. Trusted also checks what should remain: a possible watermark produces a warning while preserving the accepted image. We test failures between writes and verify that retries do not remove earlier accepted data. Our suite has three hundred and sixty-four offline tests and one isolated S3 and Chroma integration test. Combined coverage is seventy-one point eight two percent. Coverage measures executed statements, and the original six thousand and twenty-one vectors remain unchanged. This is bounded input screening, with an auditable result. It does not replace antivirus scanning or specialist review.

## 19 / A query with a traceable answer

Wassim / 18:30–19:20 / 50 seconds

*Cue: The project contribution*

Let us return to the person who started with a photograph. They can now explore related assets, move across modalities and ask a question linked to its sources. That experience rests on preserved originals, explicit transformations, quality policies and model contracts. This is EcoSentinel's contribution: connecting a useful query workflow with a data backbone we can explain and check. The repository includes a user guide, design decisions and selected validation evidence. The next evaluation would use labelled examples and specialist review before considering operational deployment. That is the scope of our prototype and the evidence behind it. Thank you. We are ready to discuss the system or show the workflow in the interface.

## Questions worth rehearsing

- Why these limits? They are explicit operational budgets for storage, decoding and CPU processing; they are not scientific cutoffs. Images also need a pixel budget because compressed MB alone does not bound decoded memory.
- Why retain possible watermarks and quiet recordings? They can contain useful wildlife evidence. Record the uncertainty instead of silently removing content. Detection is heuristic and may be wrong.
- What do reports prove? They expose decisions, provenance completeness and distribution changes. They do not certify labels, licences or biological correctness.
- What does the security gate prove? The generated executable-header case is blocked before upload. It is bounded screening, not antivirus.
- Why is a wolf among lynx image hits? CLIP ranks similarity; catalogue labels and scores do not constitute species identification. Cropped duplicates may also survive conservative quality rules.
- What is coverage? The percentage of measured source statements executed by tests; 71.82% combined is not model accuracy.
- What remains to evaluate? A labelled retrieval/answer benchmark, measured peak RAM and independent clean-machine installation.

- Why JPEG quality 95? It is a chosen encoder setting prioritising fidelity, not a measured 95% quality score. JPEG remains lossy; original bytes stay in Landing.
- Where do cropping and resampling happen? Formatted keeps image dimensions and source audio rate/channels; model adapters perform the adaptation needed for inference later. Trusted evaluates quality and duplicates.
- Why NFC, LF and UTF-8? A consistent Unicode/line-ending representation avoids encoding differences without translating, lowercasing or removing punctuation from the stored text. Text similarity features may casefold without rewriting the document.
- Why the graph bins differ from the HTML? The presentation uses fixed 20-percentage-point bins from the same recorded CSV measurements. It does not change the measured values or decisions. The source hash and bin definition are recorded in quality_charts.json.
