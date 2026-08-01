"""
pipeline/rag/layer.py
======================
Layer 3 — RAG (Retrieval-Augmented Generation)  [PASS]

Goal: For large databases, retrieve ONLY the schemas/tables relevant to the user's question.
Without this, a 414-table schema like Sepidaar won't fit in any LLM context window.

Current status: PASS — returns full schema text for all tables.

TODO (implement after enrichment):
  1. Build one text document per table using enriched descriptions:
       "Table: ACC.Account. Columns: AccountId (unique account identifier),
        Title (account name in Persian), ..."
  2. Embed all documents with OllamaEmbeddings
  3. Store in FAISS vector store, keyed by db_name
  4. On each query: embed the question, retrieve top-k similar tables
  5. Filter out sensitive tables flagged by Enrichment Layer
  6. Return schema text only for relevant tables

Implementation sketch:
  from langchain_community.vectorstores import FAISS
  from langchain_core.documents import Document

  docs = [
      Document(
          page_content=f"Table: {schema}.{table}. {description}",
          metadata={"schema": schema, "table": table, "sensitive": False}
      )
      for schema, table, description in enriched_tables
      if not sensitive
  ]

  if db_name not in self.vector_stores:
      self.vector_stores[db_name] = FAISS.from_documents(docs, self.embeddings)

  results = self.vector_stores[db_name].similarity_search(question, k=10)
  relevant_schemas = {r.metadata["schema"] for r in results}
  return introspection_result.get_schema_info_for(list(relevant_schemas))

Tuning notes:
  - k=10 is a safe default; reduce for speed, increase for complex queries
  - Always include FK-referenced tables even if not directly retrieved
  - Re-index when schema changes (detect via fingerprint comparison)
  - Consider MMR (max marginal relevance) to avoid duplicate/similar tables
"""

from pipeline.base import BaseLayer
from pipeline.introspection.layer import IntrospectionResult


class RAGLayer(BaseLayer):

    def __init__(self, llm, embeddings, db_manager):
        super().__init__(llm, embeddings, db_manager)
        self.vector_stores: dict = {}  # {db_name: FAISS} — populated when implemented

    def run(self, question: str, introspection_result: IntrospectionResult, db_name: str) -> str:
        """
        PASS: Returns full schema text for all tables.
        Replace with vector similarity search when implementing.

        Returns:
            str: Schema text in LLM-ready format (CREATE TABLE statements + sample rows)
        """
        return introspection_result.get_full_schema_info()