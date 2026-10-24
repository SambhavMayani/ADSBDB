# Data and model provenance

EcoSentinel uses a curated Iberian wildlife reference corpus, not a labelled benchmark. The reference installation has 198 accepted assets across ten configured species. Source labels and licences are provider provenance; technical acceptance does not independently verify them.

## Original data

| Source | Reference contribution | Acquisition and provenance |
|---|---|---|
| [Wikimedia Commons](https://commons.wikimedia.org/) | 100 images | `download_wikimedia_images.py`; source page/file URL, dimensions, creator, credit, licence URL and SHA-256 |
| [Xeno-canto](https://xeno-canto.org/) | 34 recordings | `download_xeno_canto_audio.py`; recording ID, recordist, source URL, location, type, quality, licence and SHA-256; acquisition needs its API key |
| [Wikipedia](https://www.wikipedia.org/) | 20 texts | `download_species_texts.py`; article URL, language, revision ID/timestamp, licence, creator and SHA-256 |
| [GBIF](https://www.gbif.org/) | 44 descriptions | Same text adapter; provider/taxon/dataset identifiers and available attribution/licence metadata |

Acquisition saves `_metadata.json` sidecars under `data/raw_dataset/<modality>/<species_id>/`. Landing copies source identity into object metadata; downstream assets and embeddings retain upstream keys and hashes. Missing attribution is not filled with an invented author or licence.

Observed metadata includes different licences, for example CC BY-SA image/text records and CC BY-NC-SA audio. A code licence would not replace asset-specific terms. Keep sidecars with any authorised dataset handoff; do not assume every record permits commercial reuse or redistribution. This review publishes no raw media or model weights.

## Reproducing data

1. **Portable technical validation:** offline tests and the synthetic `orchestration.smoke` fixture are generated from code and need no reference-data distribution.
2. **Exact reference evaluation:** obtain the authors' dataset/metadata and matching index, or reconstruct in a new isolated installation with the recorded models. Preserve the authors' original index. A handoff must include matching data and index versions.
3. **New acquisition:** run the optional adapters with configured credentials. APIs, quotas, files and revisions can change; report this new corpus separately.

The authors must ensure the supervisor can access the repository and any reference-data handoff. The [user guide](user_guide.md) provides technical validation even without that handoff. No online download location for the local corpus is implied by this repository.

## Pretrained models and decisions

No model is trained or fine-tuned on this corpus. Embeddings are generated explicitly rather than through an implicit database embedding function.

| Model | Purpose and reason | Main trade-off |
|---|---|---|
| [CLIP ViT-B/32](https://huggingface.co/sentence-transformers/clip-ViT-B-32) | Images in a 512-dimensional space aligned to language | General visual semantics, not a wildlife species classifier |
| [Multilingual CLIP](https://huggingface.co/sentence-transformers/clip-ViT-B-32-multilingual-v1) | Spanish/English text aligned to the visual space | Short visual concepts rather than long biological descriptions |
| [Multilingual E5 small](https://huggingface.co/intfloat/multilingual-e5-small) | Compact multilingual text retrieval, 384 dimensions; query/passage prefixes | CPU/storage compromise, not an empirically best model claim |
| [CLAP HTSAT unfused](https://huggingface.co/laion/clap-htsat-unfused) | Audio/text alignment, 512 dimensions; preserves non-speech retrieval | Fixed audio windows and limited language/domain coverage |
| [BLIP captioning base](https://huggingface.co/Salesforce/blip-image-captioning-base) | Independent image-to-text adapter for Task 3 | Captions can be wrong and lose visual details |
| [Qwen2.5 3B Instruct GGUF](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF) | Local generation from retrieved text; Q4_K_M reduces memory demand | Slow CPU inference, short answers, no direct pixels; model card identifies Qwen Research terms |

These choices fit the constraints and shared-space requirements; they are not the result of a broad model-selection benchmark. A native VLM or hosted model offers different visual reasoning, resource, privacy and reproducibility trade-offs.

Embedding commits are in [the manifest](../config/model_manifest.json), generation settings in [the RAG policy](../config/rag.yaml), and BLIP's revision in `multimodal_tasks/generate.py`. The GGUF SHA-256 is verified before loading. Historical null revision fields remain unchanged to preserve existing fingerprints; the manifest records observed cache revisions with that historical limitation documented.

## Delivery contents

Source, one pinned requirements file, configuration, tests, documentation, the English report and sanitised evidence summaries are versioned. `.env`, data, caches, indexes, backups and runtime logs remain ignored. Their presence on an author's machine is not part of a clean clone. See [evidence](evidence/README.md).
