"""Explicit real-model RAG acceptance: read original data, query only the snapshot."""

import argparse
import json
from pathlib import Path
import sys
import time

from exploitation_zone.contracts import ROOT
from exploitation_zone.source import TrustedRepository, create_minio_client
from multimodal_tasks.rag import RagService, validate_report_path
from multimodal_tasks.rag_model import generate
from multimodal_tasks.search import SearchService
from orchestration.audit import inventory, counts
from orchestration.files import atomic_json_write


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.add_argument(
        '--case',
        action='append',
        choices=[
            'habitat',
            'stored-image',
            'frog-image',
            'frog-identification',
            'unsupported',
            'out-of-domain',
        ],
    )
    parser.add_argument(
        '--output', type=Path, default=ROOT / 'reports/validation/rag_acceptance.json'
    )
    args = parser.parse_args(argv)
    args.output = validate_report_path(args.output)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    original = ROOT / 'data/chromadb'
    before = inventory(original)
    snapshot = ROOT / 'data/search_index'
    snapshot_counts = counts(snapshot)
    diagnostic = []

    def audited_generate(messages, policy):
        result = generate(messages, policy)
        diagnostic.append(result['text'])
        return result

    service = RagService(SearchService(snapshot), generator=audited_generate)
    report = {
        'model': service.policy.model,
        'revision': service.policy.revision,
        'policy_sha256': service.policy.fingerprint(),
        'cases': [],
        'status': 'running',
    }
    atomic_json_write(args.output, report)
    started = time.perf_counter()
    for case in args.case or [
        'habitat',
        'stored-image',
        'frog-image',
        'frog-identification',
        'unsupported',
        'out-of-domain',
    ]:
        print('RAG acceptance:', case, flush=True)
        try:
            image = None
            key = None
            if case in ('stored-image', 'frog-image', 'frog-identification'):
                repo = TrustedRepository(create_minio_client(), 'trusted-zone')
                species = 'pelophylax_perezi' if case.startswith('frog-') else 'lynx_pardinus'
                key = next(repo.list('images', species))
                repo.source_info(key)
                image = repo.get(key)
            question = {
                'out-of-domain': 'Dame una receta de pizza',
                'unsupported': '¿Cuál es la secuencia completa de nucleótidos del genoma del lince ibérico?',
                'frog-image': 'Describe el hábitat y la alimentación de las especies candidatas recuperadas, según las fuentes. No confirmes la especie de la fotografía.',
                'frog-identification': 'que animal es',
            }.get(case, '¿Cuál es el hábitat del lince ibérico, según las fuentes?')
            result = service.answer(question, image=image, input_source_key=key)
            negative = case in ('out-of-domain', 'unsupported')
            passed = result['status'] == ('abstained' if negative else 'answered')
            if negative:
                expected_reason = (
                    'query_domain_unrecognized' if case == 'out-of-domain' else 'model_abstained'
                )
                passed = passed and result['reason'] == expected_reason
            else:
                passed = passed and bool(result['claims']) and not result['validation_errors']
            report['cases'].append({'case': case, 'passed': passed, 'result': result})
            # Explicit acceptance reports preserve raw output for investigating a
            # rejected answer; the web service never displays/persists this text.
            if diagnostic:
                report['cases'][-1]['generation_diagnostic'] = diagnostic.pop()
        except Exception as error:
            report['cases'].append(
                {
                    'case': case,
                    'passed': False,
                    'error': type(error).__name__ + ': ' + str(error)[:300],
                }
            )
        atomic_json_write(args.output, report)
        print('Result:', 'passed' if report['cases'][-1]['passed'] else 'failed', flush=True)
    report['original_index_unchanged'] = before == inventory(original)
    report['snapshot_counts_unchanged'] = snapshot_counts == counts(snapshot)
    report['duration_seconds'] = round(time.perf_counter() - started, 3)
    passed = (
        all(case['passed'] for case in report['cases'])
        and report['original_index_unchanged']
        and report['snapshot_counts_unchanged']
    )
    report['status'] = 'completed' if passed else 'failed'
    atomic_json_write(args.output, report)
    print(json.dumps({key: value for key, value in report.items() if key != 'cases'}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
