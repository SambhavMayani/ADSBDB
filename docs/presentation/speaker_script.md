# EcoSentinel presentation script

English · 24 slides · target 15:00; allow approximately 15–17 minutes after rehearsal.

Read only the speech paragraphs aloud. Cues and source notes are not spoken. Questions and live CPU inference are outside the timed talk.

Mario: slides 1–8, 00:00–05:10. Sambhav: slides 9–18, 05:10–11:15. Wassim: slides 19–24, 11:15–15:00.

## 01. EcoSentinel

**Mario · 00:00–00:25 · 25 seconds**

Cue: Point to the photograph, then pause after the question

Suppose we upload this photograph and ask what the animal eats. Where should the answer come from? EcoSentinel connects the image to stored wildlife evidence and lets us inspect the sources behind the response. We will show the engineering that makes this possible.

## 02. A photograph starts the investigation

**Mario · 00:25–00:45 · 20 seconds**

Cue: The domain gives the pipeline a purpose

Our use case is a shared wildlife collection for education and biodiversity exploration. Someone can start with a photograph, find related recordings and descriptions, and ask a question grounded in those documents. We chose Iberian fauna to keep that investigation concrete.

## 03. Three modalities, one reference dataset

**Mario · 00:45–01:10 · 25 seconds**

Cue: Counts describe the reference installation

Our reference dataset contains one hundred images, thirty-four recordings and sixty-four texts across ten Iberian species. Wikimedia, Xeno-canto, Wikipedia and GBIF provide the source material. Availability is uneven: the lizard has no audio. We retain that gap and preserve attribution rather than inventing missing observations.

## 04. The EcoSentinel pipeline

**Mario · 01:10–01:45 · 35 seconds**

Cue: Follow the boundaries and the source references

The orchestrator runs sixteen steps across four zones and finishes with reconciliation. Landing preserves originals. Formatted establishes file representations. Trusted makes quality decisions. Exploitation creates searchable vectors. The first three zones use S3-compatible storage in Docker; Chroma stores the vectors. Queries open a verified copy of that persistent index to protect the audited original from internal database writes. After data updates, we explicitly refresh the copy.

## 05. Hashes and embeddings

**Mario · 01:45–02:25 · 40 seconds**

Cue: A byte fingerprint and a similarity representation answer different questions

We use two representations for different jobs. SHA-two-fifty-six fingerprints the file bytes. It helps verify integrity and build deterministic identities. An embedding represents features learned by a particular model, so nearby vectors can retrieve related content. Recompressing a photograph changes its bytes and therefore its hash, while its embedding may remain similar. That is a conceptual example, not a new measurement. Landing uses a hash prefix and filename for ingestion identity. Similarity search uses embeddings. A high similarity score does not establish an exact copy or confirm a species.

## 06. Landing identity and completion records

**Mario · 02:25–03:25 · 60 seconds**

Cue: Technical reuse has explicit conditions

Landing gives each ingestion a deterministic key: the first sixteen hexadecimal characters of SHA-two-fifty-six, followed by the original filename. Same bytes and filename produce the same key. Before uploading, we check whether that object already exists in Temporal. If Temporal is absent, a separate completion record points to its Persistent copy. We check that target and the source identity before skipping the upload. Promotion writes completion only after verifying the copied bytes. A missing target or conflicting identity produces an error. A renamed copy gets a different ingestion key, so Trusted handles content duplicates separately. The marker confirms Persistent promotion; later reconciliation checks the downstream state.

## 07. Landing: four identity cases

**Mario · 03:25–04:10 · 45 seconds**

Cue: Read each incoming photo against the already-seen photo; names are illustrative

These four cases show what technical deduplication means. Assume the source metadata matches and the first file is already recorded. Same bytes and same filename reuse the existing key, so there is no new upload. Identical bytes under another name create a new key and enter Landing. Different bytes under the same name also enter: their hash changes, so the original is not overwritten. If both change, the file enters too. Landing prevents repeated technical ingestion. Trusted still checks content duplicates and perceptual similarity. A recompressed photograph can pass Landing even when it looks unchanged.

## 08. Formatted choices for wildlife data

**Mario · 04:10–05:10 · 60 seconds**

Cue: Explain what each choice preserves and what it costs

For wildlife photographs, RGB JPEG gives us a compact, widely supported representation. Quality ninety-five prioritises visual fidelity. It remains lossy; PNG would preserve pixels and transparency instead. We keep dimensions and leave model cropping to Exploitation. Six real multiframe image sources required an explicit primary-frame policy. Audio becomes FLAC PCM sixteen: compressed PCM avoids another lossy audio encode, while preserving rate, channels and duration when possible. Higher-precision input can lose precision through quantisation. UTF-eight, consistent line endings and Unicode normalisation keep Spanish and English text readable across platforms. Text extraction loses layout. Persistent Landing keeps every complete original. Sambhav will explain the quality decisions.

## 09. Trusted: rejection or warning?

**Sambhav · 05:10–06:00 · 50 seconds**

Cue: Separate hard failures from useful ecological variation

Our Trusted policy separates rejection from warnings. Images must decode and respect a twenty-megabyte, forty-megapixel budget, with at least one hundred and twenty-eight pixels per side. Pixel count matters because compressed size alone does not bound decoding cost. Audio has a two-hundred-megabyte ceiling and text has four. These are operational budgets. Exact hashes detect identical image bytes; perceptual candidates need structural and colour confirmation. Watermark signals and quiet recordings remain visible warnings. Quiet intervals can carry ecological meaning. A later rejection or storage error preserves an earlier accepted object and records the reason for review.

## 10. Quality decisions leave an audit trail

**Sambhav · 06:00–06:20 · 20 seconds**

Cue: Show the actual report and distinguish completeness from truth

Each asset receives a quality manifest. We aggregate those records into HTML, CSV, JSON and plots. This is our recorded image report: all one hundred images remain, including thirty-two possible watermark warnings. Complete provenance fields establish traceability, not biological correctness.

## 11. Did filtering change species representation?

**Sambhav · 06:20–06:40 · 20 seconds**

Cue: Before and after measure the effect of our policy

We compare species distributions before and after Trusted because filtering could alter what users retrieve. Here, both series remain at ten images per species and the measured distribution shift is zero. This describes our small curated sample, not the distribution of wildlife populations.

## 12. Quiet intervals remain in the evidence

**Sambhav · 06:40–07:00 · 20 seconds**

Cue: The warning has an explicit consequence

Nine recordings have a high proportion of low-energy windows. We retain all thirty-four recordings, so the distributions before and after match. Removing quiet sections could erase distant calls or environmental context. The warning tells a reviewer what to inspect without rewriting the recording.

## 13. Five collections, 6,021 embeddings

**Sambhav · 07:00–07:35 · 35 seconds**

Cue: Completeness is more than a row count

Long recordings and documents produce several segments, which explains how one hundred and ninety-eight assets generate six thousand and twenty-one vectors. Each vector retains its source, asset identity, segment position and model-policy contract. Compatible reruns check exact segment coverage before reusing results. Counts alone are insufficient: a duplicated segment could hide a missing one. This contract lets us detect and recover incomplete publication without recomputing every embedding.

## 14. Three encoders, three relationships

**Sambhav · 07:35–08:25 · 50 seconds**

Cue: Model choice follows the retrieval relationship

For an image and a sentence, CLIP uses separate encoders trained to place related content in one shared space. CLAP does the same for sounds and descriptions, without treating animal calls as speech. Multilingual E-five small retrieves passages in Spanish and English. These pretrained models support our CPU deployment. Within each compatible space, we can compare vectors. Across different models, we combine their result positions using reciprocal rank fusion, rather than compare raw scores. Equal vector dimensions do not make spaces interchangeable. English descriptions generally suit CLAP better. We have not established which model is best on a labelled wildlife benchmark.

## 15. Similarity is an angle, not a probability

**Sambhav · 08:25–09:10 · 45 seconds**

Cue: The two-dimensional calculation illustrates the actual normalised-vector rule

Cosine similarity measures the angle between two vectors. We divide their dot product by their lengths. Our vectors are normalised, so the calculation becomes a dot product. In this two-dimensional example, the query is one, zero. The first candidate scores zero point nine six, the second zero point six, and the third zero. The first is most aligned; zero means perpendicular. Our actual vectors have hundreds of dimensions. Higher scores mean closer representations within that space. There is no universal cut-off for relevant wildlife, and zero point nine six is not ninety-six percent confidence.

## 16. Finding neighbours: HNSW in Chroma

**Sambhav · 09:10–10:00 · 50 seconds**

Cue: Cosine scores a pair; HNSW selects neighbours through a layered graph

The lecture distinguishes a similarity measure from a search algorithm. Cosine scores two vectors. To find neighbours among many vectors, our Chroma collections configure H-N-S-W: Hierarchical Navigable Small World. Its sparse upper layers make longer hops; denser lower layers refine the candidate neighbourhood. This is approximate search, so it can miss a true nearest neighbour. We use the database implementation and have not measured its recall on labelled wildlife queries. Our code also has an exact path for at most sixty-four eligible vectors. It compares all of them directly, avoiding a dependency on a persisted graph for tiny or newly created collections.

## 17. Task 1: a real image query

**Sambhav · 10:00–10:40 · 40 seconds**

Cue: Point out both the useful matches and the failure

This is a recorded image query using real CLIP embeddings. We exclude the entire reference asset and group segments by file. The slide shows matches at ranks one and three from five returned assets. Four catalogue labels are lynx and one is wolf; a cropped variant also survives. These results demonstrate retrieval and expose the limits of visual similarity. A high score does not verify species identity or prove that every near duplicate has been removed.

## 18. Task 2: one query, images and text

**Sambhav · 10:40–11:15 · 35 seconds**

Cue: One query returns different modalities

This text query returned four images and four texts. The illustrated image scores zero point three three two. It is a useful candidate despite scoring much lower than our image-to-image example. Query type changes the score distribution; one threshold would mislead. A diversity policy prevents text passages dominating the display. Users choose top-k from one to fifty; eight is the default, counting distinct assets. Wassim will show how retrieved evidence supports generation.

## 19. Task 3: answer from retrieved evidence

**Wassim · 11:15–12:05 · 50 seconds**

Cue: Retrieval, generation and post-validation remain separate

Task three retrieves evidence before asking Qwen to generate an answer. For image questions, CLIP retrieves visual candidates and BLIP supplies an unverified caption. E-five retrieves relevant text; we pass bounded evidence units with explicit identifiers to Qwen. The three-billion-parameter quantised model runs locally on CPU. It receives text rather than image pixels, which controls memory but loses visual detail. After generation, we validate allowed source identifiers and literal quotations. This does not prove every interpretation is correct. We distinguish supported answers, partial answers and abstention from technical failures such as timeouts.

## 20. The frog case: evidence and uncertainty

**Wassim · 12:05–12:40 · 35 seconds**

Cue: A candidate remains a hypothesis

The recorded frog case answered habitat and diet using source excerpts. The interface exposes both the candidate species and the quotations. We keep the photographic identification uncertain. A separate complete-genome request produced an abstention because the required evidence was absent. These examples test the behaviour of the full model pipeline. They are qualitative cases, not a biological accuracy benchmark. We use the recording here because CPU generation can take minutes.

## 21. The second run adds zero new vectors

**Wassim · 12:40–13:15 · 35 seconds**

Cue: The full CLI has been exercised twice

We also tested the complete command-line pipeline with isolated storage and real CPU models. Three synthetic assets produced seven vectors on the first run. The second completed all sixteen steps with zero new vectors. Reconciliation checked the resulting state. This demonstrates compatible reuse across the zones. The image is noise and the audio is a tone, so this execution test does not measure wildlife relevance.

## 22. How we tested the pipeline

**Wassim · 13:15–14:05 · 50 seconds**

Cue: Name the failure and the state we assert afterwards

Our validation has several layers. Three hundred and sixty-four offline tests use generated inputs to check contracts and failure paths. The isolated integration test runs real zone code with S3 and Chroma twice, using deterministic encoders. Separate native CPU runs check the actual model path. We inject copy mismatches, failed completion records and incomplete vector publication, then verify that retries preserve accepted data and recover missing work. Search tests check grouping, filters and exclusion of the reference. The new browser check follows top-k through real HTTP requests. The tests assert resulting state, not simply that a command returned successfully.

## 23. An input can fail before it reaches storage

**Wassim · 14:05–14:40 · 35 seconds**

Cue: The executable header is harmless test data

Here, a file called lynx dot jpg contains a harmless Windows executable header. Our Security Gate blocks it before hashing or upload; we never execute it. Other generated cases cover corrupt files, empty inputs, archive expansion and resource limits. A controlled watermark signal verifies the opposite outcome: retain the image and record a warning. Combined statement coverage is seventy-one point eight two percent. It measures code exercised, not retrieval accuracy. This screening does not replace antivirus.

## 24. A query with a traceable answer

**Wassim · 14:40–15:00 · 20 seconds**

Cue: Return to the opening question

We began by asking where an answer should come from. EcoSentinel makes that route inspectable: source material, explicit transformations, quality decisions and retrieved evidence. Our next evaluation needs expert-labelled relevance and answers, including cases where the system abstains unnecessarily.

## Questions after the talk

**Does the Landing marker prove Trusted acceptance?** It verifies completed promotion to Persistent. Downstream quality manifests and reconciliation establish later state.

**What if a copy has another name?** The content hash remains the same, but the Temporal key includes the filename. It is another technical ingest identity. Trusted applies modality-specific content deduplication.

**What are the four name/content cases?** Assuming compatible species/modality/source metadata and an existing Temporal object or valid completion record: same bytes + same name skips; same bytes + different name uploads as a new key; different bytes + same name uploads as a new key without overwriting the first; different bytes + different name uploads as a new key. The displayed hashes are calculated from two existing embedded photographs, with illustrative filenames. Missing completion targets and metadata conflicts fail instead of silently skipping. Different hashes here assume no collision in the 64-bit key prefix; the prefix is not a mathematical uniqueness guarantee.

**Does the hash in a filename describe the converted file?** The inherited filename identifies the raw asset. Each derived representation has its own content checksum where recorded.

**Why preserve all the originals?** JPEG encoding, PCM16 quantisation and text extraction can lose information. Persistent retains the source for audit and future processing.

**Does a matching vector count prove completeness?** No. We check source/policy compatibility and exact segment identities, including missing or repeated parts.

**What does top-k count?** Distinct returned assets, with a maximum of 1–50 and default 8. Mixed retrieval applies explicit diversity; the RRF constant 60 is a separate parameter.

**How is cosine calculated?** The dot product divided by both vector lengths; for unit vectors, just their dot product. The toy example uses q=(1,0) with candidates (0.96,0.28), (0.60,0.80) and (0,1). Their scores are 0.96, 0.60 and 0.00. In production, vectors have 384 or 512 dimensions. Small candidate sets use an exact dot product; larger searches use the cosine HNSW index and report 1 minus cosine distance.

**Which lecture algorithm do we use?** Chroma is configured with HNSW and cosine distance in exploitation_zone/vector_store.py. HNSW is Hierarchical Navigable Small World, an approximate nearest-neighbour graph, covered in the supplied Vector Databases lecture, pages 87–105. The exhaustive exact path for at most 64 eligible vectors corresponds to the nearest-neighbour scan in pages 31–34. We do not implement LSH, IVF or PQ for vector retrieval. SHA-256 in Landing is a cryptographic byte fingerprint, not Locality-Sensitive Hashing. We make no measured speedup or recall claim.

**What counts as very similar?** A score closer to 1 means more aligned embeddings in that compatible space. There is no calibrated universal relevance/species threshold. Recorded CLIP image-to-image scores are 0.912 for the leading lynx and 0.792 for a wolf at rank 5; the text-to-image lynx example scores 0.332. These are qualitative observations, not probabilities or universal good/bad bands.

**How can different file types be compared?** Their modality-specific encoders must align into the same model space: image/text via CLIP, audio/text via CLAP. E5, CLIP and CLAP outputs cannot be compared directly with each other. Federated retrieval combines per-model ranks as sum(1/(60+rank)), at most one contribution per asset per list. For example, ranks 1 and 3 across two lists yield 1/61 + 1/63, about 0.03227. This fusion score is not cosine or a confidence probability.

**What does 71.82% mean?** Executed Python statements across the recorded offline and integration runs. It is not biological or model accuracy.

**What is automatic in GitHub?** The configured workflow runs offline checks on Windows/Linux and isolated integration on Linux after a push or pull request. Inspect the submitted commit; local success alone does not prove remote success.

**Why can RAG abstain?** Evidence may be absent or insufficient. A technical timeout or invalid generation has a separate error state.

**Why query a copy of Chroma?** The original already persists on disk. The extra verified copy protects it from database internal writes, at a disk/freshness cost. Refresh it explicitly after data updates.
