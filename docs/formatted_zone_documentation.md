# EcoSentinel — Formatted Zone

**Implementation status:** image formatting implemented and validated; audio and text formatting pending.

This document describes the Formatted Zone contract, the implemented image transformation, operational procedures, testing, decisions, and limitations. It complements `landing_zone_documentation.md` and `decision_log.md`.

## 1. Purpose and scope

The Formatted Zone standardizes the **representation** of each modality while preserving source lineage. It reads from Persistent Landing and writes new objects to the `formatted-zone` bucket. Persistent Landing remains the immutable source of raw assets.

Formatted is **not** a quality-control stage: it does not remove duplicates, evaluate whether the animal is correctly depicted, reject blurred images, resize for a specific model, crop, or correct acquisition errors. Those concerns belong to Trusted or, for model-specific operations, downstream analytical pipelines.

The project specification requires a script per modality/format and conversion logic even when input happens to be in the target representation. For images, the chosen canonical format is JPEG.

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
- Audio and text **formatting** scripts are pending and should be developed independently with their own canonical representations and documented conversion policies. Acquisition scripts for both modalities exist in the shared repository, but their complete datasets have not been validated in this document.

## 10. Operational handoff

For image-related changes, adjust `format_images.py` and this documentation together. Do not modify common Landing scripts to add Formatted-specific behavior.

If the format contract changes (e.g. JPEG quality, alpha background policy or MPO frame extraction), document the rationale, update the format version, and plan a controlled regeneration of existing Formatted outputs rather than silently overwriting them.
