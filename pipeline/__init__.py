"""
pipeline/__init__.py
====================
Orchestrator — wires all 5 layers together.
Each layer is in its own sub-package so you can implement them one by one.

Layer status:
  [PASS]  — returns empty/passthrough so simple LLM chat works today
  [BASIC] — minimal working implementation
  [TODO]  — needs real implementation
"""

from pipeline.introspection.layer  import IntrospectionLayer
from pipeline.enrichment.layer     import EnrichmentLayer
from pipeline.rag.layer            import RAGLayer
from pipeline.sql_generation.layer import SQLGenerationLayer
from pipeline.self_correction.layer import SelfCorrectionLayer


class Pipeline:
    def __init__(self, llm, embeddings, db_manager):
        self.introspection   = IntrospectionLayer(llm, embeddings, db_manager)
        self.enrichment      = EnrichmentLayer(llm, embeddings, db_manager)
        self.rag             = RAGLayer(llm, embeddings, db_manager)
        self.sql_generation  = SQLGenerationLayer(llm, embeddings, db_manager)
        self.self_correction = SelfCorrectionLayer(llm, embeddings, db_manager)

    def run(self, question: str, db_name: str) -> dict:
        """
        Run the full pipeline for one user question.

        Returns:
            {
                "success": bool,
                "sql":     str | None,
                "result":  list[dict] | None,
                "error":   str | None,
            }
        """
        try:
            # Layer 1
            schema_raw = self.introspection.run(db_name)

            # Layer 2
            schema_enriched = self.enrichment.run(schema_raw, db_name)

            # Layer 3
            schema_relevant = self.rag.run(question, schema_enriched, db_name)

            # Layer 4
            sql = self.sql_generation.run(question, schema_relevant)

            # Layer 5
            result, final_sql = self.self_correction.run(
                sql, db_name, question, schema_relevant
            )

            return {"success": True, "sql": final_sql, "result": result, "error": None}

        except Exception as e:
            return {"success": False, "sql": None, "result": None, "error": str(e)}
