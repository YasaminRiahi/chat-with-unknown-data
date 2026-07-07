"""
pipeline/enrichment/layer.py
=============================
Layer 2 — Enrichment  [PASS]

Goal: Use LLM to generate human-readable descriptions for each column.
This replaces what BIRD benchmark does with expensive human annotators.

Example:
  Input : {"name": "F",   "type": "VARCHAR", "samples": ["M", "F"]}
  Output: {"name": "F", ..., "description": "Gender — 'M' = Male, 'F' = Female"}

Current status: PASS — returns schema unchanged so chat works today.

TODO (implement this layer next):
  1. For each table, build a prompt with column names, types, sample values
  2. Ask LLM: "Describe what each column represents in plain English"
  3. Parse response and attach descriptions to each column dict
  4. Cache results keyed by schema fingerprint (so we don't re-enrich every query)

Prompt template:
  "You are a database analyst. Given columns from table '{table}',
   describe each column based on its name, type, and sample values.
   Reply as JSON: [{\"name\": \"col\", \"description\": \"...\"}]
   Columns: {columns_json}"

Caching strategy:
  - Key: hash(db_name + table_names + column_names)
  - Store: JSON file on disk or Redis
  - Invalidate when new columns are detected
"""

from pipeline.base import BaseLayer


class EnrichmentLayer(BaseLayer):

    def run(self, schema_raw: list[dict], db_name: str) -> list[dict]:
        """
        PASS: Returns schema as-is with empty descriptions.
        Replace this with real LLM calls when implementing.
        """
        for table in schema_raw:
            for col in table["columns"]:
                col["description"] = ""  # TODO: LLM-generated description
        return schema_raw
