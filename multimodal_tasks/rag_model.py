"""Bounded CPU GGUF runtime. No implicit downloads, GPU layers or remote code."""

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import time

from exploitation_zone.contracts import ROOT
from multimodal_tasks.rag_policy import load_policy
from multimodal_tasks.rag_evidence import digest, resolve_evidence
from multimodal_tasks.rag_query import aspect_score, question_aspects

CACHE = ROOT / 'data/model_cache/gguf'


class RagResourceError(RuntimeError):
    """Expected local resource condition, safe to explain to the user."""


def available_memory_gib():
    if os.name == 'nt':
        import ctypes

        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (key, ctypes.c_ulonglong)
                for key in (
                    'total',
                    'available',
                    'page',
                    'free_page',
                    'virtual',
                    'free_virtual',
                    'extended',
                )
            ]

        value = Memory()
        value.length = ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise RuntimeError('Cannot inspect available memory')
        return value.available / 2**30
    if Path('/proc/meminfo').is_file():
        return next(
            int(line.split()[1]) / 2**20
            for line in Path('/proc/meminfo').read_text().splitlines()
            if line.startswith('MemAvailable:')
        )
    return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 2**30


def verified_model(policy):
    path = CACHE / policy.model_file
    if not path.is_file():
        raise RagResourceError(
            'Prepara el modelo RAG con python -m multimodal_tasks.rag_model --download'
        )
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != policy.model_sha256:
        raise RagResourceError(
            'El SHA-256 del modelo RAG no coincide; no se cargan pesos alterados.'
        )
    return path


def output_schema(messages, policy=None):
    policy = policy or load_policy()
    context = json.loads(messages[1]['content'])
    ids = [
        unit['evidence_id']
        for source in context['untrusted_sources']
        if source['modality'] == 'text'
        for unit in source['evidence']
    ]
    if not ids:
        raise ValueError('Generation requires textual evidence')
    claim = {
        'type': 'object',
        'properties': {
            'evidence_id': {'type': 'string', 'enum': ids},
            'text': {'type': 'string', 'maxLength': policy.max_claim_chars},
        },
        'required': ['evidence_id', 'text'],
        'additionalProperties': False,
    }
    aspects = question_aspects(context['question'])[:2]
    if len(aspects) == 1:
        return {
            'type': 'object',
            'properties': {
                'answerable': {'type': 'boolean'},
                'claims': {
                    'type': 'array',
                    'maxItems': min(2, len(question_aspects(context['question']))),
                    'items': {
                        'type': 'object',
                        'properties': {
                            'evidence_id': {'type': 'string', 'enum': ids},
                            'text': {'type': 'string', 'maxLength': policy.max_claim_chars},
                        },
                        'required': ['evidence_id', 'text'],
                        'additionalProperties': False,
                    },
                },
            },
            'required': ['answerable', 'claims'],
            'additionalProperties': False,
        }
    units = [unit for source in context['untrusted_sources'] for unit in source['evidence']]
    slots = []
    for aspect in aspects:
        ranked = sorted(
            units, key=lambda unit: (-aspect_score(unit['quote'], aspect), unit['evidence_id'])
        )
        allowed = [
            unit['evidence_id'] for unit in ranked if aspect_score(unit['quote'], aspect) > 0
        ][:3]
        if allowed:
            variant = {
                **claim,
                'properties': {
                    **claim['properties'],
                    'aspect': {'const': aspect},
                    'evidence_id': {'type': 'string', 'enum': allowed},
                },
                'required': ['aspect', 'evidence_id', 'text'],
            }
            slots.append({'oneOf': [variant, {'type': 'null'}]})
        else:
            slots.append({'type': 'null'})

    def envelope(answerable, claims):
        return {
            'type': 'object',
            'properties': {'answerable': {'const': answerable}, 'claims': claims},
            'required': ['answerable', 'claims'],
            'additionalProperties': False,
        }

    return {
        'oneOf': [
            envelope(False, {'const': []}),
            envelope(
                True,
                {
                    'type': 'array',
                    'prefixItems': slots,
                    'minItems': len(slots),
                    'maxItems': len(slots),
                },
            ),
        ]
    }


def generate(messages, policy):
    free = available_memory_gib()
    if free < policy.min_available_memory_gib:
        raise RagResourceError(
            f'RAG necesita {policy.min_available_memory_gib:g} GiB de RAM disponible; ahora hay {free:.1f}. Cierra otras aplicaciones y vuelve a intentarlo.'
        )
    path = verified_model(policy)
    schema = output_schema(messages, policy)
    from llama_cpp import Llama, LlamaGrammar, StoppingCriteriaList

    model = None
    started = time.perf_counter()
    try:
        model = Llama(
            model_path=str(path),
            n_gpu_layers=0,
            n_ctx=policy.max_input_tokens + policy.max_new_tokens + 64,
            n_threads=policy.cpu_threads,
            n_threads_batch=policy.cpu_threads,
            n_batch=256,
            use_mmap=True,
            chat_format='chatml',
            seed=0,
            verbose=False,
        )
        # Explicit ChatML keeps the measured and generated prompt identical.
        prompt = (
            ''.join(
                '<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>\n'
                for message in messages
            )
            + '<|im_start|>assistant\n'
        )
        tokens = model.tokenize(prompt.encode('utf-8'), add_bos=False, special=True)
        if len(tokens) > policy.max_input_tokens:
            raise ValueError('RAG prompt exceeds the configured token budget')
        load_seconds = time.perf_counter() - started
        tick = time.perf_counter()
        deadline = tick + policy.max_generation_seconds
        stop = StoppingCriteriaList([lambda input_ids, logits: time.perf_counter() >= deadline])
        grammar = LlamaGrammar.from_json_schema(json.dumps(schema), verbose=False)
        response = model.create_completion(
            prompt=prompt,
            grammar=grammar,
            stop=['<|im_end|>', '<|endoftext|>'],
            temperature=0.0,
            top_k=1,
            top_p=1.0,
            max_tokens=policy.max_new_tokens,
            stopping_criteria=stop,
        )
        usage = response['usage']
        raw = response['choices'][0]['text']
        return {
            'text': resolve_evidence(raw, messages),
            'raw_output_sha256': digest(raw),
            'input_tokens': usage['prompt_tokens'],
            'output_tokens': usage['completion_tokens'],
            'quantization': policy.quantization,
            'backend': 'llama.cpp CPU',
            'model_sha256': policy.model_sha256,
            'load_seconds': round(load_seconds, 3),
            'generation_seconds': round(time.perf_counter() - tick, 3),
            'deadline_reached': time.perf_counter() >= deadline,
            'finish_reason': response['choices'][0].get('finish_reason'),
            'duration_seconds': round(time.perf_counter() - started, 3),
        }
    finally:
        if model is not None:
            model.close()
        gc.collect()


def prepare(policy, *, download=False):
    if download:
        from huggingface_hub import hf_hub_download

        hf_hub_download(
            policy.model,
            filename=policy.model_file,
            revision=policy.revision,
            local_dir=str(CACHE),
            token=False,
        )
    return verified_model(policy)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args(argv)
    if args.download:
        os.environ['HF_HUB_OFFLINE'] = '0'
        os.environ['HF_HUB_DISABLE_XET'] = '1'
    policy = load_policy()
    prepare(policy, download=args.download)
    print('RAG model ready:', policy.model, policy.revision, policy.model_sha256)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
