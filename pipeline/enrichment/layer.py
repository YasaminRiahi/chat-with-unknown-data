"""
pipeline/enrichment/layer.py
=============================
Layer 2 — Enrichment  [PASS]

Goal: Use LLM to generate human-readable descriptions for each table and column.
This replaces what BIRD benchmark does with expensive human annotators.

Example:
  Input : column "F" with samples ["M", "F"]
  Output: description "Gender field — 'M' = Male, 'F' = Female"

Current status: PASS — returns IntrospectionResult unchanged.

TODO (implement this layer next):
  1. For each schema/table, build a prompt with column names, types, sample values
  2. Ask LLM to describe what each column represents in plain English
  3. Also ask LLM to flag sensitive tables (passwords, tokens, credentials)
  4. Attach descriptions and sensitivity flags to each table/column
  5. Cache results keyed by schema fingerprint to avoid re-enriching every query

Prompt template:
  "You are a database analyst. Given columns from table '{schema}.{table}',
   describe each column based on its name, type, and sample values.
   Also flag if this table contains sensitive data (passwords, tokens, PII).
   Reply as JSON: {
     'sensitivity': 'high|low',
     'reason': '...',
     'columns': [{'name': 'col', 'description': '...'}]
   }"

Caching strategy:
  - Key: hash(db_name + schema + table_name + column_names)
  - Store: JSON file on disk
  - Invalidate when new columns are detected
"""

from pipeline.base import BaseLayer
from pipeline.introspection.layer import IntrospectionResult


class EnrichmentLayer(BaseLayer):

    def run(self, introspection_result: IntrospectionResult, db_name: str) -> IntrospectionResult:
        """
        PASS: Returns IntrospectionResult unchanged.
        Replace this with real LLM calls when implementing.
        """
        return introspection_result