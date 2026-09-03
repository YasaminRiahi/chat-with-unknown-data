"""
pipeline/__init__.py
====================
Orchestrator — wires all 6 implemented layers together.
Each layer is kept in its own sub-package for focused maintenance and testing.
"""

import re

from pipeline.introspection.layer   import IntrospectionLayer
from pipeline.enrichment.layer      import EnrichmentLayer
from pipeline.rag.layer             import RAGLayer
from pipeline.rag.reranker          import CrossEncoderReranker
from pipeline.sql_generation.layer  import SQLGenerationLayer
from pipeline.self_correction.layer import SelfCorrectionLayer
from pipeline.answer_generation.layer import AnswerGenerationLayer
from pipeline.visualization.layer import VisualizationLayer


class Pipeline:
    def __init__(
        self,
        llm,
        embeddings,
        db_manager,
        enrichment_cache_dir: str = ".cache/enrichment",
        llm_enrichment_enabled: bool = True,
        enrichment_batch_size: int = 12,
        embedding_cache_dir: str = ".cache/embeddings",
        reranker_enabled: bool = False,
        reranker_model: str = "BAAI/bge-reranker-v2-m3",
        schema_linking_enabled: bool = True,
    ):
        self.introspection = IntrospectionLayer(llm, embeddings, db_manager)
        self.enrichment = EnrichmentLayer(
            llm,
            embeddings,
            db_manager,
            cache_dir=enrichment_cache_dir,
            llm_enabled=llm_enrichment_enabled,
            batch_size=enrichment_batch_size,
        )
        reranker = CrossEncoderReranker(reranker_model, enabled=reranker_enabled)
        self.rag = RAGLayer(
            llm, embeddings, db_manager, cache_dir=embedding_cache_dir,
            reranker=reranker, schema_linking_enabled=schema_linking_enabled,
        )
        self.sql_generation = SQLGenerationLayer(llm, embeddings, db_manager)
        self.self_correction = SelfCorrectionLayer(llm, embeddings, db_manager)
        self.answer_generation = AnswerGenerationLayer(llm, embeddings, db_manager)
        self.visualization = VisualizationLayer()

        # Cache: {db_name: IntrospectionResult}
        self._introspection_cache: dict = {}

    def ensure_introspection(self, db_name: str):
        """Return cached authoritative metadata, discovering it when necessary."""
        if db_name not in self._introspection_cache:
            print(f"[Pipeline] Cache miss - running introspection for '{db_name}'")
            self._introspection_cache[db_name] = self.introspection.run(db_name)
        return self._introspection_cache[db_name]

    @staticmethod
    def _qualified_table(question: str, introspection_result):
        cleaned = question.replace("[", "").replace("]", "")
        cleaned = cleaned.replace('"', "").replace("'", "").replace("`", "")
        for match in re.finditer(r"(?<!\w)([\w]+)\s*\.\s*([\w]+)(?!\w)", cleaned):
            resolved = introspection_result.resolve_table(match.group(1), match.group(2))
            if resolved:
                return resolved
        return None

    def answer_metadata_question(self, question: str, db_name: str) -> str | None:
        """Answer structural questions without embeddings, SQL, or a chat model."""
        lowered = question.casefold()
        asks_count = bool(re.search(r"\b(how many|number of|count)\b", lowered))
        asks_names = bool(re.search(r"\b(list|name|show)\b", lowered))
        asks_schema_names = asks_names or bool(
            re.search(r"\b(what are|which)\b.*\bschemas?\b", lowered)
        )
        asks_table_names = asks_names or bool(
            re.search(r"\bwhat are\b.*\btables?\b", lowered)
            or re.search(r"\bwhich tables?\s+(are|exist)\b", lowered)
        )

        if re.search(r"\b(schemas?)\b", lowered) and (asks_count or asks_schema_names):
            result = self.ensure_introspection(db_name)
            if asks_count:
                return f"There are {len(result.schemas)} schemas."
            return "\n".join(result.schemas) if result.schemas else "No user schemas were found."

        if re.search(r"\b(columns?|fields?)\b", lowered):
            result = self.ensure_introspection(db_name)
            table_key = self._qualified_table(question, result)
            if table_key:
                columns = result.get_columns(*table_key)
                if asks_count:
                    return (
                        f"{table_key[0]}.{table_key[1]} has {len(columns)} columns."
                    )
                if columns:
                    return "\n".join(column["name"] for column in columns)
                return f"No columns were found for {table_key[0]}.{table_key[1]}."

        if re.search(r"\b(tables?)\b", lowered) and (asks_count or asks_table_names):
            result = self.ensure_introspection(db_name)
            tables = result.get_all_table_names()
            if asks_count:
                return f"There are {len(tables)} tables."
            return "\n".join(tables) if tables else "No user tables were found."

        return None

    def run(self, question: str, db_name: str) -> dict:
        try:
            # Layer 1 — use cache if available
            introspection_result = self.ensure_introspection(db_name)

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

            # Layer 6
            answer = self.answer_generation.run(question, final_sql, result)

            # Layer 7 - presentation metadata only; never mutates SQL or rows.
            visualization = self.visualization.run(question, result)
            columns = list(result[0].keys()) if result else []

            return {
                "success": True, "sql": final_sql, "result": result,
                "data": {"columns": columns, "rows": result},
                "answer": answer, "visualization": visualization,
                "error": None,
            }

        except Exception as e:
            return {
                "success": False, "sql": None, "result": None,
                "data": None, "answer": None, "visualization": None,
                "error": str(e),
            }

    def clear_cache(self, db_name: str = None):
        """Clear cache for a specific DB or all DBs."""
        if db_name:
            self._introspection_cache.pop(db_name, None)
            self.rag.clear(db_name)
        else:
            self._introspection_cache.clear()
            self.rag.clear()
