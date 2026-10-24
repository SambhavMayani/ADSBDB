"""Task 3: pretrained image captioning followed by traceable multimodal retrieval."""

from __future__ import annotations
import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path
import time

MODEL = 'Salesforce/blip-image-captioning-base'
REVISION = '82a37760796d32b1411fe092ab5d4e227313294b'


def caption(image_bytes: bytes, *, allow_download=False) -> str:
    """CPU inference; model cache is offline unless explicitly authorized by CLI."""
    import torch
    from PIL import Image, ImageOps
    from transformers import BlipProcessor, BlipForConditionalGeneration

    options = {'revision': REVISION, 'local_files_only': not allow_download}
    processor = BlipProcessor.from_pretrained(MODEL, use_fast=False, **options)
    model = BlipForConditionalGeneration.from_pretrained(MODEL, **options).to('cpu').eval()
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            if source.width * source.height > 20_000_000:
                raise ValueError('Image exceeds query pixel limit')
            image = ImageOps.exif_transpose(source).convert('RGB')
            inputs = processor(images=image, return_tensors='pt')
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=48, do_sample=False, num_beams=1)
        return processor.decode(ids[0], skip_special_tokens=True)
    finally:
        del model, processor
        import gc

        gc.collect()


def describe(image_bytes, service, *, captioner=caption, allow_download=False, limit=6):
    started = time.perf_counter()
    generated = captioner(image_bytes, allow_download=allow_download)
    if not isinstance(generated, str) or not generated.strip():
        raise ValueError('The generative model returned an empty caption')
    results = service.text(generated, mode='image_text', limit=limit)
    return {
        'task': 'image_caption_and_retrieval',
        'caption': generated,
        'model': MODEL,
        'revision': REVISION,
        'input_sha256': hashlib.sha256(image_bytes).hexdigest(),
        'references': results,
        'duration_seconds': round(time.perf_counter() - started, 3),
        'limitations': 'Generated English caption; not verified species identification. References are retrieval evidence, not a factual verification of the caption.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--index', type=Path)
    parser.add_argument('--allow-model-download', action='store_true')
    args = parser.parse_args(argv)
    if args.image.stat().st_size > 10 * 1024 * 1024:
        parser.error('Image exceeds 10 MB')
    from multimodal_tasks.search import SearchService

    result = describe(
        args.image.read_bytes(), SearchService(args.index), allow_download=args.allow_model_download
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
