"""
pipeline/__init__.py
====================
Orchestrator — wires all 5 layers together.
Each layer is in its own sub-package so you can implement them one by one.

Layer status:
  [LANGCHAIN] — uses LangChain SQLDatabase
  [PASS]      — passthrough, not yet implemented
  [BASIC]     — minimal working implementation
"""

from pipeline.introspection.layer   import IntrospectionLayer
from pipeline.enrichment.layer      import EnrichmentLayer
from pipeline.rag.layer             import RAGLayer
from pipeline.sql_generation.layer  import SQLGenerationLayer
from pipeline.self_correction.layer import SelfCorrectionLayer


class Pipeline:
    def __init__(self, llm, embeddings, db_manager):
        self.introspection = IntrospectionLayer(llm, embeddings, db_manager)
        self.enrichment = EnrichmentLayer(llm, embeddings, db_manager)
        self.rag = RAGLayer(llm, embeddings, db_manager)
        self.sql_generation = SQLGenerationLayer(llm, embeddings, db_manager)
        self.self_correction = SelfCorrectionLayer(llm, embeddings, db_manager)

        # Cache: {db_name: IntrospectionResult}
        self._introspection_cache: dict = {}

    def run(self, question: str, db_name: str) -> dict:
        try:
            # Layer 1 — use cache if available
            if db_name not in self._introspection_cache:
                print(f"[Pipeline] Cache miss — running introspection for '{db_name}'")
                self._introspection_cache[db_name] = self.introspection.run(db_name)
            else:
                print(f"[Pipeline] Cache hit — skipping introspection for '{db_name}'")

            introspection_result = self._introspection_cache[db_name]

            # Layer 2
            introspection_result = self.enrichment.run(introspection_result, db_name)

            # Layer 3
            schema_text = self.rag.run(question, introspection_result, db_name)

            # Layer 4
            sql = self.sql_generation.run(question, schema_text)

            # Layer 5
            result, final_sql = self.self_correction.run(
                sql, db_name, question, schema_text
            )

            return {"success": True, "sql": final_sql, "result": result, "error": None}

        except Exception as e:
            return {"success": False, "sql": None, "result": None, "error": str(e)}

    def clear_cache(self, db_name: str = None):
        """Clear cache for a specific DB or all DBs."""
        if db_name:
            self._introspection_cache.pop(db_name, None)
        else:
            self._introspection_cache.clear()