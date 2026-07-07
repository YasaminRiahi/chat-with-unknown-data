"""
pipeline/rag/layer.py
======================
Layer 3 — RAG (Retrieval-Augmented Generation)  [PASS]

Goal: For large databases, retrieve ONLY the tables relevant to the user's question.
Without this, a 200-table schema won't fit in any LLM context window.

Current status: PASS — returns all tables (fine for small/dev DBs today).

TODO (implement after enrichment):
  1. Build one text document per table:
       "Table: customers. Columns: id (customer id), name (full name), ..."
  2. Embed all documents with OllamaEmbeddings (nomic-embed-local)
  3. Store in FAISS vector store, keyed by db_name
  4. On each query: embed the question, retrieve top-k similar tables
  5. Return only those table dicts

Implementation sketch:
  from langchain_community.vectorstores import FAISS
  from langchain.schema import Document

  docs = [Document(page_content=table_to_text(t), metadata={"table": t["table"]})
          for t in schema_enriched]

  if db_name not in self.vector_stores:
      self.vector_stores[db_name] = FAISS.from_documents(docs, self.embeddings)

  results = self.vector_stores[db_name].similarity_search(question, k=10)
  relevant = {r.metadata["table"] for r in results}
  return [t for t in schema_enriched if t["table"] in relevant]

Tuning notes:
  - k=10 is a safe default; reduce for speed, increase for complex multi-table queries
  - Consider MMR (max marginal relevance) to avoid returning duplicate/similar tables
  - Re-index when schema changes (detect via fingerprint comparison)
"""

from pipeline.base import BaseLayer


class RAGLayer(BaseLayer):

    def __init__(self, llm, embeddings, db_manager):
        super().__init__(llm, embeddings, db_manager)
        self.vector_stores: dict = {}  # { db_name: FAISS } — populated when implemented

    def run(self, question: str, schema_enriched: list[dict], db_name: str) -> list[dict]:
        """
        PASS: Returns all tables regardless of the question.
        Replace with vector similarity search when implementing.
        """
        return schema_enriched
