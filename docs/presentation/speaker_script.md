# EcoSentinel presentation script

English, 25 slides, 2,022 spoken words. Rehearsal target **18:25** (approximately 18-20 minutes). Timing is an estimate; rehearse aloud together. Questions and live CPU generation are outside the timed talk.

| Slides | Speaker | Suggested time |
|---|---|---|
| 1-9 | Mario | 00:00-06:50 |
| 10-19 | Sambhav | 06:50-14:05 |
| 20-25 | Wassim | 14:05-18:25 |

Speak only the paragraphs below. Cues guide pointing and pauses. Use the recorded examples; native CPU requests can take minutes. The allocation is a proposal.

## 1. EcoSentinel

**Mario / 00:00-00:30 / 30 seconds**

Cue: Point to the photograph, then pause after the question

Suppose we upload this photograph and ask what the animal eats. Where should the answer come from? EcoSentinel connects the image to wildlife information that we can check. We will follow that path from the original file to a search result, and finally to an answer with sources.

## 2. A photograph starts the investigation

**Mario / 00:30-01:00 / 30 seconds**

Cue: The domain gives the pipeline a purpose

That question matters outside a classroom too. A teacher preparing a wildlife lesson, or a field team reviewing an observation, may have a photograph but need a call recording or a habitat description. Those materials often sit in separate catalogues. We bring them together, using Iberian fauna as a clear and limited domain for the project.

## 3. Three modalities, one reference dataset

**Mario / 01:00-01:30 / 30 seconds**

Cue: Counts describe the reference installation

To build that collection, we gathered one hundred images, thirty-four recordings and sixty-four texts for ten Iberian species. They come from Wikimedia, Xeno-canto, Wikipedia and GBIF. The sources do not cover every species equally. The lizard, for example, has no audio. We keep these gaps visible, and preserve source information so that users can check where each record came from.

## 4. The EcoSentinel pipeline

**Mario / 01:30-02:15 / 45 seconds**

Cue: Follow the boundaries and the source references

The files pass through four zones. Landing preserves the originals, Formatted gives each type a common format, and Trusted checks quality and duplicates. Exploitation then creates search vectors. The first three zones use object storage, while Chroma stores the vectors on disk. Searches open a verified copy because Chroma can make internal writes when opened. We refresh this copy after data changes, without calculating embeddings again. The orchestrator connects all these stages in the order shown on the next slide.

## 5. The 16 steps in order

**Mario / 02:15-02:55 / 40 seconds**

Cue: Follow the six stage groups from top to bottom; do not read all names aloud

These are the sixteen steps behind that diagram. We start by checking storage and creating any missing buckets. Then we ingest local files and verify their copies in Persistent. Three formatters and three validators handle images, audio and text. Five indexing steps build the collections, and the last step checks that accepted files and vector parts agree. Everything runs in sequence. A failure stops later steps, and a rerun checks what already completed. Optional acquisition adds three downloads after storage setup. We will now explain the decisions inside those stages.

## 6. Hashes and embeddings

**Mario / 02:55-03:45 / 50 seconds**

Cue: Explain why identity comes before model inference

Before we look inside Landing, there is an important distinction between hashes and embeddings. At ingestion, we need to check file identity. SHA-two-fifty-six reads the bytes once in small blocks, without decoding the media or loading a neural model. That makes the check cheap and predictable, although we have not measured a speed ratio. An embedding answers a later question: whether content is related. Saving a photograph again can change its hash while leaving its meaning almost unchanged. We therefore use hashes for identity and integrity, then embeddings for similarity.

## 7. Landing: file identity and verified copies

**Mario / 03:45-04:40 / 55 seconds**

Cue: Copy, verify, then mark complete

Landing turns that identity into an object key: the first sixteen hexadecimal characters of the hash, followed by the filename. On a rerun, we first look for that object in Temporal and check its source information. If it has already left Temporal, a completion record points to its copy in Persistent. We check that the target exists before skipping it. The copying step verifies the bytes before writing this record, so a broken copy cannot look complete. This proves completion of Landing; Trusted makes its own decision later.

## 8. Landing: four identity cases

**Mario / 04:40-05:35 / 55 seconds**

Cue: The filename is part of the submitted-file identity

The filename in that key explains these four cases. Same bytes and same name reuse the existing record. Same bytes with a different name enter again because we preserve the identity of the submitted file, including its name. That costs some storage, but Trusted will check duplicate content later. Different bytes with the same name also enter, under a new hash, so they cannot overwrite the first version. When both change, we get a new record too. Landing handles simple identity checks before the more detailed quality work.

## 9. Formatted choices for wildlife data

**Mario / 05:35-06:50 / 75 seconds**

Cue: Connect every format choice to wildlife data

Once the originals are safe, Formatted gives each type a common representation. For photographs, JPEG at quality ninety-five balances detail and file size. It is usually efficient for photos, but still loses information, so we keep the original and its dimensions. MPO needs special handling because one file can contain several photographs. We use its first photograph and preserve the others upstream. For audio, a faint call may sit behind rain, wind or other animals. FLAC avoids another lossy encoding step, while keeping background sound and quiet sections. Our sixteen-bit conversion can still reduce precision from richer sources. Finally, UTF-eight preserves Spanish and English text. For JSON, we first try recognised content fields and only fall back to the longest string when none is found. With the formats consistent, Sambhav will explain the quality decisions.

## 10. Trusted: rejection or warning?

**Sambhav / 06:50-07:45 / 55 seconds**

Cue: Separate hard failures from useful ecological variation

Trusted decides whether a file is usable and which issues need a warning. Images must decode, stay below twenty megabytes and forty megapixels, and have at least one hundred and twenty-eight pixels on each side. We check pixels as well as bytes because a small compressed file can still need a lot of memory. Audio has a two-hundred-megabyte cap and text has four. These are practical budgets for our local system, rather than scientifically optimal thresholds. Hashes find exact duplicates. For similar images, a perceptual hash finds candidates, then we check structure and colour. Darkness, possible watermarks and quiet audio usually remain warnings, preserving material that may still be useful.

## 11. Quality decisions leave an audit trail

**Sambhav / 07:45-08:20 / 35 seconds**

Cue: Show the actual report and distinguish completeness from truth

Those decisions need to be visible, so every checked asset gets a JSON quality record. We use the records to create an HTML report, CSV measurements and plots. Here is the actual image report. All one hundred reference images remain accepted, including thirty-two possible watermark warnings. Source fields are complete, which helps us trace the records. It does not prove that every source label is correct. The charts make the effects of our decisions easier to inspect.

## 12. Did filtering change species representation?

**Sambhav / 08:20-08:50 / 30 seconds**

Cue: Before and after measure the effect of our policy

This chart compares species counts before and after Trusted. If a rule removed many images from one species, we would see that imbalance here. In our reference batch, both bars show ten images per species and the measured distribution change is zero. That tells us about the effect of our filtering on this selected dataset, rather than about animal populations in nature.

## 13. Quiet intervals remain in the evidence

**Sambhav / 08:50-09:15 / 25 seconds**

Cue: The warning has an explicit consequence

Audio shows why a warning can be more useful than rejection. Nine recordings contain many quiet intervals, yet a distant animal call can itself be quiet. Removing those sections could also lose background context. We therefore keep all thirty-four recordings and record the warning for inspection. Once these quality decisions are recorded, the accepted material is ready for indexing.

## 14. Five collections, 6,021 embeddings

**Sambhav / 09:15-09:55 / 40 seconds**

Cue: Completeness is more than a row count

A long recording or document needs several searchable segments. This is why one hundred and ninety-eight files produce six thousand and twenty-one embeddings across five collections. Each vector keeps its file identity, source and segment position. On a rerun, we check compatibility and the complete set of expected segments. Counting rows alone could miss a missing segment hidden by a duplicate. These checks let us repair incomplete work without calculating every vector again.

## 15. Three encoders, three relationships

**Sambhav / 09:55-10:50 / 55 seconds**

Cue: Model choice follows the retrieval relationship

The five collections use three model families because the relationships are different. CLIP connects photographs with descriptions, while CLAP connects sounds with descriptions, including animal calls. Multilingual E-five small handles detailed Spanish and English text retrieval. All three run on CPU. Their outputs stay in compatible spaces: CLIP and CLAP may both produce five-hundred-and-twelve numbers, but the coordinates mean different things. When searching across models, we combine result positions rather than comparing raw scores. Inside each space, we use cosine similarity.

## 16. Similarity is an angle, not a probability

**Sambhav / 10:50-11:40 / 50 seconds**

Cue: The two-dimensional calculation illustrates the actual normalised-vector rule

Cosine compares the directions of two vectors. We divide their dot product by their lengths. Since we normalise our vectors to unit length, the calculation becomes just the dot product. In this two-dimensional example, the candidates score zero point nine six, zero point six and zero. The first points closest to the query, while the last is perpendicular. Our real vectors have hundreds of components, but the same rule applies. The score describes closeness in that model space. It does not give a probability that the animals belong to the same species.

## 17. Finding neighbours: HNSW in Chroma

**Sambhav / 11:40-12:40 / 60 seconds**

Cue: Cosine scores a pair; HNSW selects neighbours through a layered graph

Cosine scores a pair of vectors, but we also need a way to find good candidates. Chroma uses H-N-S-W, a graph with several levels. It makes large jumps at the upper levels and explores nearby candidates below. This saves a full scan for larger sets, but the search is approximate. When sixty-four or fewer vectors remain after filtering, our code compares every vector instead. We chose sixty-four as a small, bounded fallback for tiny collections that may lack a saved graph. It is a practical cap, not an optimum established by comparing thirty-two, sixty-four and one hundred and twenty-eight.

## 18. Task 1: a real image query

**Sambhav / 12:40-13:20 / 40 seconds**

Cue: Point out both the useful matches and the failure

Here is what that search produces in Task one using real CLIP embeddings. We exclude the reference file and return each other file once. Four of these five results have a lynx label, while one has a wolf label. A cropped version also remains. The example shows useful visual matches, but also why we should not treat similarity as species identification or assume that every near duplicate has disappeared.

## 19. Task 2: one query, images and text

**Sambhav / 13:20-14:05 / 45 seconds**

Cue: One query returns different modalities

Task two uses an aligned space to connect different types of files. Here, one text query returns four images and four texts. The displayed image scores zero point three three two. It can still be useful even though that score is lower than the image-to-image example, because query types have different score ranges. We reserve room for both modalities so that text chunks do not fill the list. Users can request one to fifty distinct files, with eight as the default. Wassim will now show how retrieved material supports a generated answer.

## 20. Task 3: answer from retrieved evidence

**Wassim / 14:05-15:00 / 55 seconds**

Cue: Same preparation in memory, no stored query

Task three retrieves evidence before asking Qwen to answer. An uploaded image first receives the shared JPEG conversion in memory, without being stored. Quality issues produce warnings, while invalid files and resource limits stop the request. We reuse a stored Trusted image unchanged. CLIP then finds visual candidates, BLIP produces an automatic caption, and E-five retrieves text evidence. Qwen receives that selected text and its source identifiers, rather than image pixels. We check the returned quotations and references, while recognising that a correct quotation does not guarantee a correct interpretation.

## 21. The frog case: evidence and uncertainty

**Wassim / 15:00-15:40 / 40 seconds**

Cue: A candidate remains a hypothesis

This recorded frog example shows that distinction. The answer describes habitat and diet using source quotations, while the candidate species remains a hypothesis about the photograph. When we asked for the complete genome instead, the system declined because the evidence was missing. These cases show how the model pipeline behaves, rather than measuring general accuracy. They were recorded before the query-preparation update. We use the saved examples in the talk because a fresh CPU response can take minutes.

## 22. The second run adds zero new vectors

**Wassim / 15:40-16:20 / 40 seconds**

Cue: The full CLI has been exercised twice

Useful answers are only one part of the project. We also need a pipeline that can run again safely. In an earlier isolated CPU demonstration, three synthetic files produced seven vectors on the first run. The second run completed all sixteen steps and added zero new vectors. The final check confirmed that the stored files and vector parts agreed. The image was noise and the audio was a tone, so this tests repeat execution, rather than wildlife relevance.

## 23. How we tested the pipeline

**Wassim / 16:20-17:15 / 55 seconds**

Cue: Current offline evidence versus earlier native runs

We test failure cases as well as successful runs. The current offline suite passes four hundred and sixty-nine tests. The latest additions check conflicting source records, missing copies, failed storage requests and incomplete vector sets. They verify that existing data stays intact. Query tests also compare prepared bytes with the actual Formatted output and check limits before conversion. Earlier integration and CPU runs provide separate evidence for real storage and models. Offline coverage is seventy-two point three seven percent of measured statements. We use it to find gaps, while the assertions tell us whether the expected behaviour holds.

## 24. An input can fail before it reaches storage

**Wassim / 17:15-18:00 / 45 seconds**

Cue: The executable header is harmless test data

One concrete failure case is this file called lynx dot jpg, containing a harmless Windows executable header. The Security Gate blocks it before hashing or upload, and the test never executes it. Other cases cover corrupt files, empty inputs and oversized archives. Compare that with a possible watermark: we keep the image and warn the user because it may still contain useful wildlife information. These different outcomes reflect the purpose of each rule. The gate checks inputs; it does not replace antivirus.

## 25. A query with a traceable answer

**Wassim / 18:00-18:25 / 25 seconds**

Cue: Return to the opening question

We began with a photograph and asked where the answer should come from. EcoSentinel makes that route inspectable, from the original file and its processing decisions to the retrieved sources. Our next evaluation needs expert-labelled queries, including useful questions that the system fails to answer. Thank you.

## Questions after the talk

**Does the Landing marker prove Trusted acceptance?** It records a verified copy in Persistent. Downstream quality manifests and reconciliation establish later state.

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

**Why not 100% coverage?** The current offline suite executes 3,897 of 5,385 measured statements (72.37%). This reveals untested code paths, not the percentage of working features. Some paths need separate integration or real-model checks, and others remain untested. We added 32 failure/boundary cases without shrinking the measured scope. Even 100% statement coverage would not prove every outcome was asserted or that retrieval is accurate.

**What is automatic in GitHub?** The configured workflow runs offline checks on Windows/Linux and isolated integration on Linux after a push or pull request. Inspect the submitted commit; local success alone does not prove remote success.

**Why can RAG abstain?** Evidence may be absent or insufficient. A technical timeout or invalid generation has a separate error state.

**Why query a copy of Chroma?** The original already persists on disk. The extra verified copy protects it from database internal writes, at a disk/freshness cost. Refresh it explicitly after data updates.


**Why FLAC for wildlife?** Faint calls may overlap with rain, wind or other animals. We avoid an extra lossy audio encode and keep quiet intervals and background context. FLAC preserves the selected PCM16 values; conversion from 24-bit or float can still lose precision. It cannot restore information already lost in MP3.

**Is JPEG always smaller or equally accurate?** No. It is usually efficient for photographs, and quality 95 is our explicit compromise. PNG preserves pixels and alpha. We have no measured JPEG-versus-PNG retrieval benchmark.

**Do queries pass through storage zones?** No. They reuse conversion and measurement functions in memory. Invalid files and resource-limit violations stop the query; quality issues return warnings. An already stored Trusted JPEG is reused unchanged. No uploaded file enters MinIO or the index.

**Are the new results a fresh native-model benchmark?** No. The current 469-test offline run checks preparation and service contracts with generated data and model doubles. The real-model examples are separately dated earlier observations.


**Why exactly 64 for exhaustive search?** It is a small engineering cap for the fallback, not a benchmarked optimum. At 512 dimensions, 64 float32 vectors contain 32,768 components (128 KiB of vector payload, excluding overhead). It avoids relying on a persisted graph for tiny segments. We scan at 64 or fewer eligible vectors after filters and use HNSW at 65 or more. Tests cover both sides, including filtered collections.

**Which are the 16 steps?** Slide 5 lists them in order. Storage: connection, buckets. Landing: local ingest, verified Persistent copy. Formatted: images, audio, text. Trusted: images, audio, text. Index: images, text, audio, image/text, audio/text. Finally reconcile. Acquisition adds three downloads after storage setup, making 19. This is sequential execution, not parallel branches.
