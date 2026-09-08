"""Rebuild feature-based evaluation reports offline, preserving recorded metrics."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.query_features import annotate, DESCRIPTIONS, VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.dataset.read_text(encoding='utf-8-sig')
    dataset = json.loads(source)
    questions = dataset['records']
    records = [json.loads(line) for line in args.checkpoint.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    for name, items in [('dataset', questions), ('checkpoint', records)]:
        if len({r['id'] for r in items}) != len(items):
            raise ValueError(f'Duplicate IDs in {name}; reconcile explicitly before reporting.')
    lookup = {r['id']: r for r in records}
    if set(lookup) != {r['id'] for r in questions}:
        raise ValueError('Dataset/checkpoint IDs differ. No files changed.')
    for q in questions:
        if any(q[k] != lookup[q['id']][k] for k in ('question', 'reference_sql')):
            raise ValueError(f"Question/reference changed since execution: {q['id']}. No files changed.")
    # Import report functions only. Never construct runtime, models or DB clients.
    from evaluation.run_evaluation import write_reports
    annotate(questions)
    annotate(records)
    legacy = {q['id']: q.get('difficulty') for q in questions}
    for r in questions + records:
        r.pop('difficulty', None)
    dataset['metadata'].update(question_count=len(questions),
        intent_count=len({q['intent_id'] for q in questions}),
        classification={'version': VERSION, 'method': 'reference_sql_lexical_plus_explicit_typo_marker',
            'multi_label': True, 'feature_count_is_difficulty': False})
    args.output.mkdir(parents=True, exist_ok=True)
    backup = args.output / 'questions_before_classification.json'
    if not backup.exists():
        backup.write_text(source, encoding='utf-8')
    manifest = {'mode': 'offline_reclassification', 'dataset': str(args.dataset.resolve()),
        'source_checkpoint': str(args.checkpoint.resolve()),
        'source_checkpoint_sha256': hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
        'classification_version': VERSION, 'metrics_recomputed_by_execution': False,
        'feature_definitions': DESCRIPTIONS, 'legacy_difficulty': legacy}
    write_reports(args.output, records, manifest)
    (args.output / 'checkpoint.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    # Preserve existing formatting and only replace each difficulty field.
    import re
    matches = list(re.finditer(r'"difficulty"\s*:\s*"[^"]*"', source))
    if len(matches) == len(questions):
        for match, q in reversed(list(zip(matches, questions))):
            replacement = ', '.join(json.dumps(k) + ': ' + json.dumps(q[k])
                for k in ('features', 'feature_count', 'join_count', 'classification_version'))
            source = source[:match.start()] + replacement + source[match.end():]
        source = re.sub(r'"question_count"\s*:\s*\d+', '"question_count": ' + str(len(questions)), source, count=1)
        source = re.sub(r'"intent_count"\s*:\s*\d+', '"intent_count": ' + str(dataset['metadata']['intent_count']), source, count=1)
        source = re.sub(r'("metadata"\s*:\s*\{)', lambda m: m[1] + '\n        "classification": ' + json.dumps(dataset['metadata']['classification']) + ',', source, count=1)
        args.dataset.write_text(source, encoding='utf-8')
    else:
        args.dataset.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'questions': len(questions), 'report': str(args.output / 'report.html'),
        'feature_counts': {k: sum(k in r['features'] for r in records) for k in DESCRIPTIONS}}, indent=2))


if __name__ == '__main__':
    main()
