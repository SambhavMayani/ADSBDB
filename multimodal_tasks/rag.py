"""Task 3: retrieval BEFORE generation, bounded context and verifiable source quotes."""

import argparse
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
import uuid
from datetime import datetime, timezone

from multimodal_tasks.generate import (
    caption as caption_image,
    MODEL as CAPTION_MODEL,
    REVISION as CAPTION_REVISION,
)
from multimodal_tasks.rag_evidence import (
    build_messages,
    digest,
    domain_hint,
    pack_evidence,
    species_mentions,
    validate_generation,
)
from multimodal_tasks.rag_model import generate
from multimodal_tasks.rag_policy import load_policy
from multimodal_tasks.rag_query import (
    expand_passages,
    image_query_plan,
    lexical_rankings,
    question_aspects,
    visual_candidates,
)
from multimodal_tasks.search import fuse_rankings
from exploitation_zone.contracts import ROOT

LOGGER = logging.getLogger('ecosentinel.rag')


def validate_report_path(path):
    target = Path(path).resolve()
    if target.suffix.lower() != '.json' or any(
        target.is_relative_to(ROOT / folder) for folder in ('data', 'minio_data', '.git')
    ):
        raise ValueError(
            'Export JSON reports outside data/, minio_data/ and .git/, for example reports/validation/'
        )
    return target


class RagService:
    def __init__(self, search, *, policy=None, captioner=caption_image, generator=generate):
        self.search, self.policy = search, policy or load_policy()
        self.captioner, self.generator = captioner, generator
        self._lock = threading.Lock()

    def answer(self, question, *, image=None, input_source_key=None):
        if not isinstance(question, str) or not 3 <= len(question.strip()) <= 1000:
            raise ValueError('La pregunta debe tener entre 3 y 1000 caracteres')
        if image is not None and (
            not isinstance(image, bytes) or not 1 <= len(image) <= 10 * 1024 * 1024
        ):
            raise ValueError('Imagen de consulta inválida o mayor de 10 MB')
        if image is not None:
            from io import BytesIO
            from PIL import Image

            with Image.open(BytesIO(image)) as source:
                if source.width * source.height > 20_000_000:
                    raise ValueError('La imagen supera 20 megapíxeles')
                source.verify()
        if input_source_key is not None:
            from exploitation_zone.contracts import source_parts

            source_parts(input_source_key, 'images')
            if image is None:
                raise ValueError('A stored-image reference requires its image bytes')
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('Another RAG request is running')
        try:
            return self._answer(question.strip(), image, input_source_key)
        finally:
            self._lock.release()

    def _answer(self, question, image, input_source_key):
        start = time.perf_counter()
        timings = {}
        result = {
            'task': 'retrieval_augmented_generation',
            'request_id': uuid.uuid4().hex,
            'started_at_utc': datetime.now(timezone.utc).isoformat(),
            'status': 'abstained',
            'question': question,
            'answer': '',
            'claims': [],
            'references': [],
            'validation_errors': [],
            'policy_sha256': self.policy.fingerprint(),
            'model': self.policy.model,
            'revision': self.policy.revision,
            'quantization': self.policy.quantization,
            'input_sha256': hashlib.sha256(image).hexdigest() if image else None,
            'input_source_key': input_source_key,
            'caption': None,
            'visual_candidates': [],
            'limitations': 'Las citas de las respuestas aceptadas se contrastan con los extractos; esto no prueba la veracidad semántica ni identifica la especie. La imagen se interpreta mediante BLIP, no directamente por el LLM.',
        }

        def finish(reason):
            result.update(
                reason=reason,
                timings=timings,
                duration_seconds=round(time.perf_counter() - start, 3),
            )
            result['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
            if not result['answer']:
                if result['status'] == 'error':
                    result['answer'] = {
                        'generation_timeout': 'Se han recuperado fuentes, pero la generación agotó el tiempo disponible antes de completar una respuesta válida.',
                        'generation_token_limit': 'Se han recuperado fuentes, pero la generación alcanzó el límite de salida antes de completar una respuesta válida.',
                    }.get(
                        reason,
                        'Se han recuperado fuentes, pero no se ha podido validar la respuesta generada. Consulta el diagnóstico y vuelve a intentarlo.',
                    )
                else:
                    result['answer'] = (
                        'El sistema no ha obtenido una respuesta suficientemente respaldada para esta consulta.'
                    )
            LOGGER.info(
                'RAG %s: status=%s reason=%s duration=%.3fs',
                result['request_id'],
                result['status'],
                reason,
                result['duration_seconds'],
            )
            return result

        if image:
            LOGGER.info('RAG %s: describing query image locally', result['request_id'])
            with self.search.lock:
                self.search.encoders.release_all()
                tick = time.perf_counter()
                visual = self.captioner(image, allow_download=False)
            if not isinstance(visual, str) or not visual.strip():
                raise ValueError('The visual model returned an empty description')
            result.update(
                caption=visual[:400], caption_model=CAPTION_MODEL, caption_revision=CAPTION_REVISION
            )
            timings['caption_seconds'] = round(time.perf_counter() - tick, 3)
            if not domain_hint(visual):
                return finish('visual_domain_unrecognized')
        elif not domain_hint(question):
            return finish('query_domain_unrecognized')

        tick = time.perf_counter()
        LOGGER.info('RAG %s: retrieving evidence from the search snapshot', result['request_id'])
        rankings = []
        if image:
            visual_rows = self.search.media(
                image, 'images', mixed=True, limit=self.policy.retrieval_candidates
            )
            rankings.append(visual_rows)
            result['visual_candidates'] = visual_candidates(visual_rows)
        mentioned = species_mentions(question)
        focus = mentioned[0] if len(mentioned) == 1 else None
        if image:
            candidate_ids = [candidate['species_id'] for candidate in result['visual_candidates']]
            plan = image_query_plan(question, [focus] if focus else candidate_ids)
            if focus:
                plan[-1] = (question, focus)
        else:
            plan = [(question, focus)]
        text_rankings = [
            self.search.text(
                query, mode='text', limit=self.policy.retrieval_candidates, species=species
            )
            for query, species in plan
        ]
        lexical_info = {'lexical_records_scanned': 0, 'lexical_scan_truncated': False}
        if image:
            scopes = (
                [focus]
                if focus
                else [candidate['species_id'] for candidate in result['visual_candidates']]
            )
            lexical, lexical_info = lexical_rankings(self.search, scopes, question, self.policy)
            text_rankings.extend(lexical)
        rankings.extend(text_rankings)
        if not image:
            rankings.append(
                self.search.text(
                    question,
                    mode='image_text',
                    limit=self.policy.retrieval_candidates,
                    species=focus,
                )
            )
        fused = fuse_rankings(rankings)
        sources = pack_evidence(expand_passages(fused, text_rankings, question), self.policy)
        result['references'] = sources
        result['retrieval'] = {
            'method': 'RRF',
            'k': 60,
            'candidate_counts': [len(rows) for rows in rankings],
            **lexical_info,
            'explicit_species_filter': focus,
            'text_query_plan': [
                {'query': query, 'species_scope': species} for query, species in plan
            ],
            'source_count': len(sources),
            'context_chars': sum(len(row['excerpt']) for row in sources),
        }
        timings['retrieval_seconds'] = round(time.perf_counter() - tick, 3)
        if (
            sum(len(row['excerpt']) for row in sources if row['modality'] == 'text')
            < self.policy.min_text_chars
        ):
            return finish('insufficient_text_evidence')
        messages = build_messages(question, result['caption'], sources, policy=self.policy)
        context = json.loads(messages[1]['content'])['untrusted_sources']
        units = [unit for source in context for unit in source['evidence']]
        result['retrieval'].update(
            evidence_units=len(units), evidence_chars=sum(len(unit['quote']) for unit in units)
        )
        if not units:
            return finish('insufficient_text_evidence')
        serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        result.update(
            prompt_sha256=digest(serialized),
            context_sha256=digest(json.dumps(sources, sort_keys=True)),
        )
        # Release search encoders before loading the instruction model.
        with self.search.lock:
            self.search.encoders.release_all()
            tick = time.perf_counter()
            LOGGER.info(
                'RAG %s: generating with %s evidence sources', result['request_id'], len(sources)
            )
            generated = self.generator(messages, self.policy)
        timings['generation_seconds'] = round(time.perf_counter() - tick, 3)
        claims, errors = validate_generation(
            generated['text'],
            sources,
            max_claim_chars=self.policy.max_claim_chars,
            max_claims=min(2, len(question_aspects(question))),
        )
        result['validation_errors'] = errors
        result['generation'] = {key: value for key, value in generated.items() if key != 'text'}
        result['generation']['output_sha256'] = digest(generated['text'])
        if errors:
            reason = errors[0]
            if reason != 'model_abstained':
                result['status'] = 'error'
                if reason == 'invalid_json' and generated.get('deadline_reached'):
                    reason = 'generation_timeout'
                elif reason == 'invalid_json' and generated.get('finish_reason') == 'length':
                    reason = 'generation_token_limit'
            return finish(reason)
        try:
            payload = json.loads(generated['text'])
        except ValueError:  # The validator also accepts fenced JSON for compatibility.
            payload = {}
        missing = payload.get('missing_aspects', [])
        result.update(
            status='partial' if missing else 'answered',
            claims=claims,
            missing_aspects=missing,
            answer='\n\n'.join(f'{claim["text"]} [{claim["source_id"]}]' for claim in claims),
        )
        return finish('partial_evidence' if missing else 'validated_citations')


def main(argv=None):
    import sys

    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--image', type=Path)
    source.add_argument('--trusted-key')
    parser.add_argument('--index', type=Path)
    parser.add_argument('--output', type=Path, help='Explicitly export a query/result report')
    args = parser.parse_args(argv)
    if args.output:
        args.output = validate_report_path(args.output)
    image = None
    if args.image:
        if args.image.stat().st_size > 10 * 1024 * 1024:
            parser.error('Image exceeds 10 MB')
        image = args.image.read_bytes()
    if args.trusted_key:
        from webapp.server import validate_key, load_media

        key = validate_key(args.trusted_key)
        if not key.startswith('images/'):
            parser.error('Select an image from Trusted')
        image, _ = load_media(key)
    from multimodal_tasks.search import SearchService

    result = RagService(SearchService(args.index)).answer(
        args.question, image=image, input_source_key=args.trusted_key
    )
    if args.output:
        from orchestration.files import atomic_json_write

        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
