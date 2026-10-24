"""Small, inspectable query plans and lexical evidence ranking; no classification."""

import re
import unicodedata


def words(text):
    plain = unicodedata.normalize('NFKD', text.lower())
    return set(re.findall(r'[a-z]+', ''.join(c for c in plain if not unicodedata.combining(c))))


ASPECTS = {
    'habitat': (
        'habitat habitats vive viven habita habitan donde distribution distribucion',
        'habitat habitats live lives living aquatic freshwater rivers ponds lakes forest forests wetland scrubland '
        'habita habitan vive viven charcas lagunas rios arroyos humedales agua bosque',
        'habitat distribution hábitat distribución',
    ),
    'diet': (
        'alimentacion alimenta alimentan alimentarse dieta diet feeding eat eats food',
        'diet food feed feeding feeds eats eat prey insect insects invertebrates '
        'alimenta alimentan alimentacion dieta presas insectos invertebrados',
        'diet feeding alimentación dieta',
    ),
    'behavior': (
        'comportamiento comporta comportan behaviour behavior actividad activity',
        'behaviour behavior activity nocturnal diurnal solitary territorial '
        'comportamiento actividad nocturno nocturna diurno diurna solitario territorial',
        'behavior activity comportamiento actividad',
    ),
    'profile': (
        '',
        'species scientific named called frog lynx wolf owl lizard '
        'especie nombre cientifico llamada llamado rana lince lobo buho lagarto',
        'description scientific common name descripción características',
    ),
}

STOPWORDS = words(
    'el la los las un una unos unas de del y o en por para que es son se su sus '
    'al con como cual cuales esta este estos estas segun sobre no si '
    'describe explica dime confirmes confirma imagen fotografia fuentes documentos '
    'especie especies candidatas candidatos recuperadas recuperados '
    'the a an and or in of to for is are it its this that with from '
    'describe explain image photo sources documents candidate candidates retrieved'
)


def question_aspects(question):
    query = words(question)
    aspects = [name for name, (triggers, _, _) in ASPECTS.items() if query & words(triggers)]
    normalized = ' '.join(re.findall('[a-z]+', unicodedata.normalize('NFKD', question.lower())))
    if any(
        phrase in normalized
        for phrase in (
            'que animal',
            'que especie',
            'what animal',
            'what species',
            'identifica',
            'identify',
        )
    ):
        aspects.insert(0, 'profile')
    return aspects or ['profile']


def aspect_score(text, aspect):
    return len(words(text) & words(ASPECTS[aspect][1]))


def content_words(question):
    return words(question) - STOPWORDS


def image_query_plan(question, candidate_ids):
    """Search candidate biology per aspect, keeping an unfiltered fallback.

    Species filters scope searches ABOUT hypotheses; they do not identify the image.
    At most two candidates and three aspects, plus the original question.
    """
    plan = [
        (f'{candidate.replace("_", " ")} {ASPECTS[aspect][2]}', candidate)
        for candidate in list(dict.fromkeys(candidate_ids))[:2]
        for aspect in question_aspects(question)
    ]
    return plan + [(question, None)]


def visual_candidates(rows):
    """Expose corpus labels as retrieval hypotheses, without confidence percentages."""
    import yaml
    from exploitation_zone.contracts import ROOT

    catalog = yaml.safe_load((ROOT / 'config/species.yaml').read_text(encoding='utf-8'))['species']
    names = {entry['id']: entry for entry in catalog}
    candidates = {}
    images = [row for row in rows if row.get('modality') == 'images'][:2]
    for row in images:
        species = row.get('species_id')
        if species not in names:
            continue
        entry = names[species]
        candidate = candidates.setdefault(
            species,
            {
                'species_id': species,
                'scientific_name': entry['scientific_name'],
                'common_name': entry['common_name_es'],
                'reference_keys': [],
            },
        )
        if row.get('source_key') and row['source_key'] not in candidate['reference_keys']:
            candidate['reference_keys'].append(row['source_key'])
    return list(candidates.values())


def expand_passages(fused, text_rankings, question):
    """Keep asset RRF order while recovering different aspect passages per asset."""
    records, scores = {}, {}
    for ranking in text_rankings:
        for rank, row in enumerate(ranking, 1):
            records.setdefault(row['asset_id'], {})[row['id']] = row
            scores[row['id']] = scores.get(row['id'], 0.0) + 1 / (60 + rank)
    output = []
    for row in fused:
        passages = list(records.get(row['asset_id'], {}).values())
        if row.get('modality') != 'text' or not passages:
            output.append({**row, 'fusion_score': row['score']})
            continue
        ordered, seen = [], set()
        for aspect in question_aspects(question):
            ranked = sorted(
                passages,
                key=lambda p: (-aspect_score(p['snippet'], aspect), -scores[p['id']], p['id']),
            )
            best = next(
                (p for p in ranked if p['id'] not in seen and aspect_score(p['snippet'], aspect)),
                None,
            )
            if best:
                ordered.append(best)
                seen.add(best['id'])
        ordered.extend(
            sorted(
                (p for p in passages if p['id'] not in seen),
                key=lambda p: (-scores[p['id']], p['id']),
            )
        )
        output.extend({**passage, 'fusion_score': row['score']} for passage in ordered)
    return output


def lexical_rankings(search, candidate_ids, question, policy):
    """Bounded hybrid retrieval over stored text, with no new vectors or model.

    This complements E5 when scientific names or chunk boundaries obscure a
    requested aspect. Lexical scores participate only via ranks, never as cosine.
    """
    rankings, scanned, truncated = [], 0, False
    for species in list(dict.fromkeys(candidate_ids))[:2]:
        data = search.collection('text').get(
            where={'species_id': species},
            limit=policy.max_lexical_records + 1,
            include=['documents', 'metadatas'],
        )
        truncated |= len(data['ids']) > policy.max_lexical_records
        rows = [
            {'id': rid, **md, 'snippet': document or '', 'space': 'text'}
            for rid, md, document in zip(
                data['ids'][: policy.max_lexical_records],
                data['metadatas'][: policy.max_lexical_records],
                data['documents'][: policy.max_lexical_records],
            )
        ]
        scanned += len(rows)
        for aspect in question_aspects(question):
            ranked = [
                {**row, 'score': aspect_score(row['snippet'], aspect), 'score_type': 'lexical'}
                for row in rows
            ]
            ranked = [row for row in ranked if row['score'] > 0]
            ranked.sort(key=lambda row: (-row['score'], row['asset_id'], row['id']))
            if ranked:
                rankings.append(ranked[: policy.retrieval_candidates])
    return rankings, {'lexical_records_scanned': scanned, 'lexical_scan_truncated': truncated}
