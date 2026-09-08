"""Offline, deterministic feature labels for the benchmark's T-SQL SELECTs.

Labels describe reference SQL, not generated SQL. This is a lexical classifier,
not a SQL validator. Comments, string literals and quoted identifiers are masked
before operator matching. Typo labels require explicit benchmark metadata/IDs.
"""
import re
from statistics import mean

VERSION = 1
DESCRIPTIONS = {
    'join': 'Combines tables with JOIN',
    'multi_join': 'Uses two or more JOINs',
    'outer_join': 'Uses LEFT, RIGHT or FULL JOIN',
    'aggregation': 'Uses COUNT, SUM, AVG, MIN or MAX',
    'group_by': 'Groups rows',
    'order_by': 'Sorts results',
    'top_limit': 'Limits results with TOP, LIMIT or FETCH',
    'filter': 'Filters rows with WHERE',
    'having': 'Filters groups with HAVING',
    'distinct': 'Removes duplicates with DISTINCT',
    'date_operation': 'Extracts, converts or compares date/time values',
    'null_handling': 'Explicit IS NULL, COALESCE or ISNULL',
    'pattern_match': 'Uses LIKE',
    'range_filter': 'Uses BETWEEN or inequality comparisons',
    'conditional': 'Uses CASE or IIF',
    'subquery': 'Contains multiple SELECTs outside a set operation',
    'cte': 'Uses a common table expression',
    'set_operation': 'Uses UNION, INTERSECT or EXCEPT',
    'window': 'Uses an OVER clause',
    'typo': 'Intentional spelling error in the benchmark input',
    'simple_select': 'Plain projection without the other SQL features',
}


def classify(record):
    raw = record.get('reference_sql', '')
    tokens = re.findall(r"--[^\n]*|/\*[\s\S]*?\*/|N?'(?:''|[^'])*'|\[(?:\]\]|[^\]])*\]|\"(?:\"\"|[^\"])*\"|[^'\[\"/-]+|.", raw, re.I)
    literals = [t for t in tokens if re.match(r"N?'", t, re.I)]
    sql = ''.join(' ' if t.startswith(('--', '/*', '[', '"')) or re.match(r"N?'", t, re.I) else t for t in tokens).upper()
    rules = {
        'join': r'\bJOIN\b', 'multi_join': None,
        'outer_join': r'\b(?:LEFT|RIGHT|FULL)\s+(?:OUTER\s+)?JOIN\b',
        'aggregation': r'\b(?:COUNT|SUM|AVG|MIN|MAX)\s*\(',
        'group_by': r'\bGROUP\s+BY\b', 'order_by': r'\bORDER\s+BY\b',
        'top_limit': r'\b(?:TOP|LIMIT|FETCH)\b', 'filter': r'\bWHERE\b',
        'having': r'\bHAVING\b', 'distinct': r'\bDISTINCT\b',
        'date_operation': r'\b(?:YEAR|MONTH|DAY|DATEPART|DATEADD|DATEDIFF|DATETRUNC|DATEFROMPARTS|GETDATE|DATETIME|DATE)\b',
        'null_handling': r'\b(?:COALESCE|ISNULL)\s*\(|\bIS\s+(?:NOT\s+)?NULL\b',
        'pattern_match': r'\bLIKE\b', 'range_filter': r'\bBETWEEN\b|>=|<=|(?<![<>=!])[<>](?![<>=])',
        'conditional': r'\bCASE\b|\bIIF\s*\(',
        'cte': r'^\s*;?\s*WITH\b', 'set_operation': r'\b(?:UNION|INTERSECT|EXCEPT)\b',
        'window': r'\bOVER\s*\(',
    }
    found = {k for k, pattern in rules.items() if pattern and re.search(pattern, sql)}
    joins = len(re.findall(r'\bJOIN\b', sql))
    if joins >= 2:
        found.add('multi_join')
    if len(re.findall(r'\bSELECT\b', sql)) > 1 and 'set_operation' not in found:
        found.add('subquery')
    if any(re.search(r'\d{4}-\d{2}-\d{2}', t) for t in literals):
        found.add('date_operation')
    if not found:
        found.add('simple_select')
    if '_typo_' in record.get('id', '') or record.get('intentional_typo') is True:
        found.add('typo')
    return {'features': sorted(found), 'feature_count': len(found), 'join_count': joins,
            'classification_version': VERSION}


def annotate(records):
    for record in records:
        record.update(classify(record))
    return records


def feature_summary(records):
    result = {}
    for label in DESCRIPTIONS:
        items = [r for r in records if label in r.get('features', [])]
        if not items:
            continue
        def metric(key):
            values = [r.get('metrics', {}).get(key) for r in items]
            values = [v for v in values if v is not None]
            return round(mean(values), 6) if values else None
        attempted = sum(bool(r.get('correction', {}).get('attempted')) for r in items)
        recovered = sum(r.get('metrics', {}).get('initial_ex') == 0 and r.get('metrics', {}).get('final_ex') == 1 and bool(r.get('correction', {}).get('attempted')) for r in items)
        initial, final = metric('initial_ex'), metric('final_ex')
        result[label] = {'description': DESCRIPTIONS[label], 'questions': len(items),
            'scored_questions': sum(r.get('metrics', {}).get('final_ex') is not None for r in items),
            'initial_execution_accuracy': initial, 'execution_accuracy': final,
            'correction_gain': round(final-initial, 6) if initial is not None and final is not None else None,
            'correction_attempted': attempted, 'recovered_questions': recovered,
            'recovery_per_attempt': recovered/attempted if attempted else None,
            'table_recall': metric('table_recall'), 'column_recall': metric('column_recall'),
            'errors': sum(bool(r.get('error')) for r in items)}
    return result
