"""Versioned RAG settings, independent of the historical embedding contracts."""

from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import re

from exploitation_zone.contracts import ROOT


@dataclass(frozen=True)
class RagPolicy:
    version: str = '1'
    model: str = 'Qwen/Qwen2.5-3B-Instruct-GGUF'
    revision: str = '7dabda4d13d513e3e842b20f0d435c732f172cbe'
    quantization: str = 'Q4_K_M'
    model_file: str = 'qwen2.5-3b-instruct-q4_k_m.gguf'
    model_sha256: str = '626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d'
    max_input_tokens: int = 3072
    max_new_tokens: int = 320
    max_generation_seconds: int = 120
    cpu_threads: int = 4
    min_available_memory_gib: float = 2.5
    retrieval_candidates: int = 10
    max_sources: int = 6
    max_source_chars: int = 1400
    max_context_chars: int = 4800
    min_text_chars: int = 120
    max_evidence_units: int = 8
    max_evidence_chars: int = 1600
    max_claim_chars: int = 240
    max_lexical_records: int = 128

    def __post_init__(self):
        if self.version != '1':
            raise ValueError('Unsupported RAG policy version')
        bounds = {
            'max_input_tokens': (512, 4096),
            'max_new_tokens': (64, 512),
            'max_generation_seconds': (10, 300),
            'cpu_threads': (1, 8),
            'retrieval_candidates': (4, 30),
            'max_sources': (2, 10),
            'max_source_chars': (200, 2000),
            'max_context_chars': (500, 6000),
            'min_text_chars': (50, 1000),
            'max_evidence_units': (2, 16),
            'max_evidence_chars': (500, 3000),
            'max_claim_chars': (80, 320),
            'max_lexical_records': (16, 512),
        }
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Invalid RAG setting: {name}')
        if (
            self.model != 'Qwen/Qwen2.5-3B-Instruct-GGUF'
            or not isinstance(self.revision, str)
            or not re.fullmatch('[0-9a-f]{40}', self.revision)
        ):
            raise ValueError('Use the supported model and an immutable commit')
        if self.quantization != 'Q4_K_M' or self.model_file != 'qwen2.5-3b-instruct-q4_k_m.gguf':
            raise ValueError('The CPU runtime requires the supported Q4_K_M GGUF')
        if not isinstance(self.model_sha256, str) or not re.fullmatch(
            '[0-9a-f]{64}', self.model_sha256
        ):
            raise ValueError('Expected an immutable model SHA-256')
        if (
            type(self.min_available_memory_gib) not in (int, float)
            or not 2 <= self.min_available_memory_gib <= 16
        ):
            raise ValueError('Invalid RAG memory reserve')
        if (
            self.max_sources > self.retrieval_candidates
            or self.min_text_chars > self.max_context_chars
        ):
            raise ValueError('Inconsistent RAG context policy')

    def fingerprint(self):
        raw = json.dumps(asdict(self), sort_keys=True).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()


def load_policy(path=None):
    import yaml

    data = yaml.safe_load(Path(path or ROOT / 'config/rag.yaml').read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Expected RAG settings object')
    try:
        return RagPolicy(**data)
    except TypeError as error:
        raise ValueError('Unknown RAG settings') from error
