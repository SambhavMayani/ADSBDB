# EcoSentinel — Formatted Zone

**Implementation status:** images implemented and validated end-to-end (100 objects); audio and text scripts implemented and regression-tested locally, with MinIO end-to-end validation still pending.

This document describes the Formatted Zone contract, the implemented image transformation, operational procedures, testing, decisions, and limitations. It complements `landing_zone_documentation.md` and `decision_log.md`.

## 1. Purpose and scope

The Formatted Zone standardizes the **representation** of each modality while preserving source lineage. It reads from Persistent Landing and writes new objects to the `formatted-zone` bucket. Persistent Landing remains the immutable source of raw assets.

Formatted is **not** a quality-control stage: it does not remove duplicates, evaluate whether the animal is correctly depicted, reject blurred images, resize for a specific model, crop, or correct acquisition errors. Those concerns belong to Trusted or, for model-specific operations, downstream analytical pipelines.

The project specification requires modality-specific scripts and conversion logic even when input already has the target representation. The canonical formats are JPEG/RGB for images, FLAC/PCM16 for audio, and plain UTF-8/LF/NFC text.

## 2. Current implementation

| Item | Value |
|---|---|
| Script | `formatted_zone/format_images.py` |
| Source bucket | `landing-zone` |
| Source prefix | `persistent_landing/images/` |
| Destination bucket | `formatted-zone` |
| Destination prefix | `images/` |
| Input extensions | `.jpg`, `.jpeg`, `.png`, `.webp` |
| Accepted internal encodings | JPEG, PNG, WEBP, MPO |
| Canonical encoding | JPEG |
| Canonical filename extension | `.jpg` |
| Canonical pixel mode | RGB |
| JPEG encoder quality | 95 |
| Dimensions | Preserved |
| Orientation | No EXIF transpose; metadata retained when available |
| Transparent pixels | Composited over a white background |
| MPO policy | Export first/primary frame only |
| Original raw object | Retained in Persistent Landing |

The source key is not inferred from its filename extension alone: Pillow identifies the actual internal encoding. This matters because six files ending in `.jpg` were detected internally as MPO.

## 3. Data flow and object keys

```text
landing-zone/
└── persistent_landing/
    └── images/<species_id>/
        └── <source>$<species>$<UTC_timestamp>$<hash>.<source_extension>
                   |
                   | read bytes + decode + canonical JPEG encode
                   v
formatted-zone/
└── images/<species_id>/
    └── <source>$<species>$<UTC_timestamp>$<hash>.jpg
```

The destination mirrors the species directory and reuses the original Persistent filename stem. The changed extension describes the *new output encoding*; the hash embedded in the filename remains the **source asset's raw hash**, not the checksum of the transformed JPEG.

Persistent objects are **never deleted** during formatting. This supports raw-data preservation, lineage, investigation of conversion issues and reproducible reprocessing.

## 4. Image conversion policy

### 4.1 JPEG and `.jpg`

JPEG is suitable for the mostly photographic wildlife collection, is widely supported, and typically requires substantially less storage than lossless PNG for similar photographs. The principal trade-off is lossy recompression. Therefore, original source files remain accessible in Persistent Landing.

All outputs use the `.jpg` extension, including assets originally stored as `.jpeg`, `.png`, `.webp`, or JPEG-compatible MPO content.

### 4.2 RGB pixel mode

The transformation decodes source pixels and produces RGB JPEG output. This makes subsequent image decoding consistent, including inputs with palette or alpha modes.

### 4.3 Transparency

JPEG does not support an alpha channel. For transparent source pixels, the implementation composites the source image onto an opaque white background. This is a **format-compatibility policy** rather than a semantic quality correction, and the choice of white can affect the displayed appearance of transparent source material.

### 4.4 JPEG quality 95

`quality=95` is a **JPEG encoder setting** and is not a measured image-quality score or a requirement in the assignment. It favors visual fidelity while still encoding to JPEG. Conversion can still alter pixel values, even for already-JPEG input.

### 4.5 Dimensions and orientation

No resizing or cropping is performed. The conversion does not call `ImageOps.exif_transpose()`. Existing EXIF orientation data is written to the output when present; the image pixels are not explicitly rotated in Formatted. Thus display orientation may depend on whether downstream viewers honor EXIF metadata.

Quality-related orientation corrections, if required, should be evaluated in Trusted with explicit criteria.

### 4.6 MPO files

During the full image run, six files with `.jpg` extension were identified internally as MPO (Multi-Picture Object):

- Four under `aquila_chrysaetos`, with two internal frames each.
- Two under `canis_lupus`, with three internal frames each.

The agreed transformation uses **only the primary frame** (`seek(0)`) to produce one canonical JPEG per Persistent object. The other frames are not exported to Formatted. However, the complete multi-image source is still preserved in Persistent Landing.

This keeps a simple one-to-one correspondence between source objects and formatted objects. It is a known limitation if later tasks require stereo or other secondary MPO images. For these objects, the output metadata records `original_format=mpo`.

## 5. Metadata and lineage

The script validates that each Persistent object provides the source fields:

```text
modality
species_id
source_name
asset_hash
```

It checks that `modality=images` and that `species_id` matches the source object path. Other Persistent metadata are copied forward, including available ingestion/filename traceability fields. The script relies on those fields being set correctly upstream; it does not independently authenticate the original provider.

The output object adds metadata including:

| Field | Purpose |
|---|---|
| `source_persistent_key_encoded` | URL-encoded key of the raw Persistent object |
| `original_format` | Actual internal encoding detected by Pillow (`jpeg`, `png`, `webp`, `mpo`) |
| `formatted_format` | `jpeg` |
| `color_mode` | `rgb` |
| `jpeg_quality` | `95` |
| `format_version` | Formatting-contract version (`1`) |
| `formatted_at` | UTC timestamp of the conversion |

The Persistent source key is URL encoded because MinIO/S3 user metadata travels via HTTP headers and keys can contain characters that should not be placed directly in metadata header values.

**Important:** do not treat `asset_hash` from Persistent metadata as a checksum of the Formatted JPEG; it identifies the input raw asset.

## 6. Incremental execution and failure handling

`format_images.py` scans Persistent Landing using paginated object listing. For each source object:

1. Build the deterministic `.jpg` destination key.
2. Validate required Persistent metadata, including a match between the object path and `species_id`.
3. Inspect the destination by direct `head_object`.
4. If the destination exists with compatible lineage and format-policy metadata, a JPEG content type, and a nonempty object size, skip it.
5. If it does not exist, read, convert, upload and verify its byte length.
6. Log conversion, skip or error and continue.

An existing destination with conflicting metadata is treated as an error **rather than overwritten**. This reduces accidental data loss and highlights incompatibilities when the transformation policy changes.

`--max-items` limits **new successful conversions** (or new planned conversions in dry-run), not the number of scanned input objects. `Discovered` can therefore be greater than `--max-items` when previous outputs are skipped.

`--dry-run` lists/plans pending operations without writing to `formatted-zone`. Note that preview mode does not perform a full image decode, so a dry-run alone cannot prove that source bytes will convert successfully.

## 7. Execution

Prerequisites: Docker storage running, project `.env` configured, virtual environment active and Pillow installed from `requirements.txt`.

```bash
# Preview one pending conversion without writing data
python formatted_zone/format_images.py --dry-run --max-items 1

# Convert one pending image
python formatted_zone/format_images.py --max-items 1

# Process all pending images
python formatted_zone/format_images.py
```

Rerunning the final command should skip existing compatible outputs. The script prints counters:

```text
Discovered
Converted
Skipped
Planned
Errors
```

The implementation exits with status 1 when processing reports one or more errors. Unexpected connection/setup failures may also stop execution.

## 8. Validation performed

The following checks have been carried out against the actual local object-store environment:

1. Dry-run with `--max-items 1`: one planned conversion and no errors.
2. Real conversion of one image: JPEG, RGB, `quality=95`, source lineage and Persistent source existence confirmed.
3. Incremental run: an existing output skipped and a later pending image converted.
4. Initial full run: **94 formatted outputs, 6 failures**, all due to MPO encodings.
5. Inspection of local raw images: four two-frame MPO files and two three-frame MPO files.
6. MPO first-frame support added in the locally validated version; one pending conversion tested successfully.
7. Remaining conversions completed without errors.
8. Final object-level validation: **100 valid JPEG RGB objects**, ten per species, `.jpg` extension, appropriate formatted metadata and lineage field; **zero validation errors**.

Final validated image state:

| Repository | Image objects |
|---|---:|
| Persistent Landing | 100 raw source objects |
| Formatted Zone | 100 canonical JPEG objects |

This confirms functional completion of image formatting. It does **not** imply that semantic image quality, license compliance, duplicate quality, pixel-perfect equality or all downstream transformations have been validated.

## 9. Technical limitations and follow-up

- JPEG recompression is lossy. The original raw files are preserved for future reprocessing.
- Embedded source hashes refer to raw bytes, not new JPEG bytes.
- White compositing can alter the visual appearance of previously transparent images.
- Secondary MPO frames are not exported to Formatted; this is an explicit 1:1 policy.
- EXIF metadata may influence viewer orientation, even though the script does not rotate pixels.
- Existing-output checks validate metadata, declared JPEG content type and nonempty size, but do not decode or recompute a full checksum for every skipped output on each run.
- Storage/lineage metadata preservation depends on information provided by earlier stages.
- Audio and text formatting scripts are now implemented and documented below; their completed object-store datasets have not yet been validated in this document.

## 10. Operational handoff

For image-related changes, adjust `format_images.py` and this documentation together. Do not modify common Landing scripts to add Formatted-specific behavior.

If the format contract changes (e.g. JPEG quality, alpha background policy or MPO frame extraction), document the rationale, update the format version, and plan a controlled regeneration of existing Formatted outputs rather than silently overwriting them.


## 11. Audio formatting (`format_audio.py`)

### 11.1 Representation and rationale

The script reads `landing-zone/persistent_landing/audio/<species_id>/<stem>.<ext>` and writes `formatted-zone/audio/<species_id>/<stem>.flac`, without modifying or deleting the source.

The canonical representation is **FLAC with 16-bit signed PCM**. FLAC itself is lossless: it can preserve the *16-bit PCM samples provided to the encoder* without further compression loss. **It does not restore lost detail from MP3/AAC/Opus, and conversion to PCM16 can quantize higher-precision PCM sources (e.g. 24-bit WAV).** The raw source remains in Persistent for fidelity-critical reprocessing. The 16-bit target is an explicit standardization choice rather than a universal losslessness guarantee.

- Sample rate and channel count are not deliberately changed; resampling and downmixing are deferred until model-specific downstream processing.
- Only the first audio stream is mapped from multi-stream media. Cover art, chapters and original container-level tags are not copied into the FLAC output; retained technical lineage is in S3 metadata.
- When available, ffmpeg decodes MP3, WAV, FLAC, OGG/Vorbis, Opus, M4A/AAC, WMA, AIFF, WebM/Matroska, AMR, CAF and AC3. libsndfile (`soundfile`) is the fallback for the subset supported by the installed version. Supported extensions do not guarantee that every codec variant is decodable.
- Basic magic-byte detection takes precedence over a recognized filename extension, but an unrecognized header can fall back to the extension; validation ultimately relies on successful decoding and FLAC inspection.

### 11.2 Verification and storage

For each source, the script checks Persistent modality, species, provenance and asset hash. It reads the raw bytes, decodes the selected audio stream, encodes FLAC/PCM16, and checks that the resulting file has samples and the expected format/subtype. It uploads the output, then checks stored byte length using `head_object`. **A matching byte length is not a cryptographic content-integrity check.**

By default, it skips existing formatted objects **only when** the metadata identifies the exact Persistent key and matching canonical format/version, and the object has the expected MIME type and nonempty size. On conflicts it reports an error instead of overwriting. `--force` intentionally replaces an existing output; use it only when reformatting is planned.

### 11.3 Audio commands

```bash
python formatted_zone/format_audio.py --dry-run --max-items 1
python formatted_zone/format_audio.py --species bubo_bubo --max-items 1
python formatted_zone/format_audio.py
# Only when deliberately regenerating previous outputs:
python formatted_zone/format_audio.py --force
```

## 12. Text formatting (`format_text.py`)

### 12.1 Representation and supported inputs

The script reads `landing-zone/persistent_landing/text/<species_id>/<stem>.<ext>` and writes `formatted-zone/text/<species_id>/<stem>.txt`. Outputs are UTF-8 without BOM, with LF line endings, Unicode NFC, excluded control characters removed, and exactly one final newline. Raw sources remain unchanged.

Parsers cover `.txt`, `.text`, Markdown, HTML/XHTML, XML, JSON, JSONL/NDJSON, PDF with extractable text, DOCX and ODT. Binary formats are recognized by PDF signature or ZIP container members when possible; text parsing generally follows the extension.

- HTML converts visible markup into text and omits style/script content.
- Markdown removes common markup, but is **not** a full CommonMark parser; complicated documents may not preserve all semantics.
- XML extracts element text. DOCX and ODT extract paragraph text; sophisticated layout and document features may be lost.
- PDF uses `pypdf` to extract an existing text layer. Scanned/image-only PDFs are not OCR'd and cause an explicit failure.
- Plain text is decoded using BOM/UTF-8, then a Windows-1252 fallback and additional heuristics. This fallback is aimed at the current Spanish/English material; it is **not** a guaranteed language-independent encoding detector.

Text extraction and markup removal are **necessarily nonreversible**. Formatted produces normalized document text, while semantic correctness, near-duplicates, irrelevant passages and content quality remain Trusted responsibilities.

### 12.2 JSON policy

The JSON extraction rule is hybrid:

1. Traverse objects breadth-first and look for standard keys such as `text`, `content`, `body`, `description`, `summary`, `extract` and `abstract`. The shallowest matching level wins; key priority decides ties.
2. If none is found, recursively select the **longest nonempty string** as a heuristic fallback.

Arrays of documents and JSON Lines are processed record-by-record and combined with blank lines. A list of strings attached to a prioritized key is joined into paragraphs. HTML embedded in a selected JSON string is converted to visible text.

**Limitation:** the longest string is not guaranteed to be the desired descriptive content. This heuristic is explicitly a fallback for unknown schemas; raw JSON remains in Persistent.

### 12.3 Verification and text commands

The formatter checks required Persistent metadata, source species identity and technical hash. It writes canonical UTF-8 text, checks the destination object size and records extraction method/encoding/JSON path metadata. Existing-output lineage/version checks and conflict behavior mirror the audio formatter.

```bash
python formatted_zone/format_text.py --dry-run --max-items 1
python formatted_zone/format_text.py --species lynx_pardinus --max-items 1
python formatted_zone/format_text.py
# Only for deliberately planned regeneration:
python formatted_zone/format_text.py --force
```

## 13. Cross-modal operational contract

The formatters run independently, after their respective raw objects have completed Persistent Landing. They never remove Persistent sources. Output keys mirror modality/species/filename stem while replacing only the extension. The embedded filename hash is derived from the **raw source**, not the transformed bytes.

Each new audio/text output retains the available common Persistent metadata (`modality`, `species_id`, `source_name`, `asset_hash`, ingestion timestamp and original filename key where present), and records:

| Field | Audio / text meaning |
|---|---|
| `source_persistent_key_encoded` | Encoded exact source S3 key |
| `source_format`, `original_format` | Detected source format |
| `canonical_format` | `flac_pcm16` or `txt_utf8_lf_nfc` |
| `formatted_format` | `flac` or `txt` |
| `formatter_version`, `format_version` | Current audio/text formatter policy (`1.0`) |
| `formatted_timestamp`, `formatted_at` | UTC formatting timestamp |
| Modality-specific properties | Audio: decoder, sample rate, channel count, frames, duration; text: encoding, extraction method, character count, optional encoded JSON path |

The additional `original_format`, `formatted_format`, `format_version` and `formatted_at` fields are **nonbreaking metadata aliases**, inspired by the earlier image contract, for easier downstream integration. Historical audio/text outputs written by earlier variants may not have the aliases until intentionally regenerated. Images currently use `format_version=1` and distinct image-specific fields; versions are not a single global counter.

All formatters check the existing destination before performing expensive work. The revised audio/text versions also verify object lineage and compatible policy before skipping, consistent with the image formatter. A destination whose key could correspond to two inputs with different extensions is treated as a conflict, not silently overwritten. In a future multi-source expansion, such collisions may require a new explicit key convention.

`--max-items` counts **new conversions** or **new planned conversions** in a dry-run; existing compatible outputs do not count. `--dry-run` does not upload anything, and **does not prove that input decoding will succeed**. Use `--force` cautiously as it permits overwrites.

All scripts accept the project's `S3_ENDPOINT_URL`; audio and text also accept `MINIO_ENDPOINT` as a fallback for compatibility. Required dependencies for the audio/text scripts are `boto3`, `python-dotenv`, `soundfile`, `imageio-ffmpeg`, and `pypdf`; `charset-normalizer` is an optional text decoding helper if installed (typically supplied by `requests`). Audio conversion may still depend on the runtime availability of an ffmpeg decoder for less common codecs.

## 14. Evidence, limitations and next validation

**Verified locally during this review:** Python syntax of both revised scripts; 12 focused offline regression tests including JSON extraction, WAV-to-FLAC PCM16 conversion, metadata path validation, existing-output conflicts, dry-run limits and incremental reexecution against an in-memory S3 substitute. These tests exercised no live object-store operations.

**Reported by the contributor but not independently re-run during this review:** 36 pre-existing tests passed. The contributor's acquisition run produced 64 local text assets (20 Wikipedia and 44 GBIF). Neither statement should be presented as independently verified end-to-end MinIO integration.

**Still required for a full operational sign-off:** install/check project requirements; run audio/text `--dry-run --max-items 1` and actual `--max-items 1` against local SILO/MinIO; verify FLAC stream properties and text bytes in `formatted-zone`; re-run for incremental skips; finally process/validate the entire actual acquired dataset and report per-species results and errors. Audio acquisition may not achieve four recordings for each of the ten species using Xeno-canto alone.

No assertions of completed audio/text full-batch conversion should be added to the README or final report before those checks pass.
