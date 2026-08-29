# chat-with-unknown-data

Zero-shot Text-to-SQL on unknown databases.

## Setup

```bash
pip install -r requirements.txt
```

Create a Groq API key for chat in the [Groq console](https://console.groq.com/keys).
Install [Ollama](https://ollama.com/) for local embeddings, then pull BGE-M3:

```bash
ollama pull bge-m3
```

Copy the example environment file:

```bash
copy .env.example .env
```

Put the Groq key in `.env`. The defaults are `openai/gpt-oss-120b` on Groq
for chat/SQL/answers and local `bge-m3` on Ollama for multilingual
Persian/English embeddings. Override them with `CHAT_MODEL`, `EMBEDDING_MODEL`,
and `OLLAMA_BASE_URL`. Keep `.env` private and never put API keys in frontend
code. Groq's free tier is intended for development and demonstrations.

Every Groq chat call and Ollama embedding call is appended as one JSON object to
`logs/model_calls.jsonl`. Entries contain the exact request payload, operation,
latency, response or error, and provider-reported token usage when available.
Embedding vectors themselves are not logged. Change the location with
`MODEL_LOG_PATH`. These logs can contain schema names, query results, and user
data, so keep the `logs/` directory private (it is ignored by Git).

On the first query for a database, the enrichment layer asks the configured chat
model for conservative table and column descriptions in small JSON batches.
Descriptions are saved under `.cache/enrichment/`, keyed by each table's DDL
fingerprint, and reused across restarts. Only new or changed tables are sent for
enrichment. Set `LLM_ENRICHMENT_ENABLED=false` to use metadata-only enrichment,
or tune batch size with `ENRICHMENT_BATCH_SIZE`.

Table and column embeddings are stored under `.cache/embeddings/`. On later
application starts, unchanged metadata is loaded from that cache instead of
being embedded again. Changing the embedding model or changing table metadata
automatically rebuilds only the affected vectors. Override the location with
`EMBEDDING_CACHE_DIR`. Failed batches are retried one document at a time; rare
NaN-producing metadata text is safely reformatted and cached without changing
the underlying schema identifiers.

Retrieval first selects at most eight relevant tables, then selects a compact
set of relevant columns while always retaining primary and foreign keys. Tables
with at most 30 columns are included completely; wider tables retain at least
the top 20 semantically ranked columns plus required structural columns and
close identifier variants. A shared 21,000-character schema budget prevents
wide-table combinations from exceeding the chat-model request limit. An
explicit `schema.table` mention bypasses semantic table selection. Structural
questions such as listing schemas, counting tables, or listing all columns of
an explicitly named table are answered directly from SQLAlchemy introspection
without an embedding or chat-model call.

Table retrieval also compares compound identifiers with close-scoring base
entities (for example, `ContractCoefficientItem` versus `Coefficient`) and
prefers the base entity when derivative qualifiers were not requested. SQL
generation uses SQL Server Unicode literals (`N'...'`) for Persian and other
non-ASCII values.

Retrieval is hybrid: dense BGE-M3 cosine results and local BM25 lexical results
are combined with Reciprocal Rank Fusion for both tables and columns. The best
30 table candidates are then scored by the multilingual
`BAAI/bge-reranker-v2-m3` cross-encoder before the existing dynamic table
selection and foreign-key expansion run. The reranker is downloaded lazily by
`sentence-transformers` on the first full retrieval. Set
`RERANKER_ENABLED=false` to retain hybrid retrieval without downloading or
running the reranker, or change `RERANKER_MODEL` to another compatible
cross-encoder.

Table retrieval prints `[RAG][Trace]` lines for the dense, BM25, fused,
model-reranked, and rule-adjusted rankings, followed by the final threshold and
its survivors. These traces make it possible to identify the exact stage where
a required table drops out during retrieval evaluation.

When a valid query returns no rows because an exact text value is slightly
wrong, the self-correction layer performs one bounded lookup in the exact
referenced text column. It compares real values with Persian-aware
normalization and fuzzy scoring, then permits the model to substitute only a
high-confidence value observed in that column. Invalid column names continue
through the normal schema-grounded SQL error correction path.

## Run

```bash
uvicorn api.main:app --reload --port 8000
```

Then open `frontend/index.html` in your browser.

## API docs

FastAPI auto-generates docs at: http://localhost:8000/docs

## Pipeline layer status

| Layer | Status | File |
|---|---|---|
| 1 — Introspection | ✅ Implemented | `pipeline/introspection/layer.py` |
| 2 — Enrichment | ✅ Implemented | `pipeline/enrichment/layer.py` |
| 3 — RAG | ✅ Implemented | `pipeline/rag/layer.py` |
| 4 — SQL Generation | ✅ Implemented | `pipeline/sql_generation/layer.py` |
| 5 — Self-Correction | ✅ Implemented | `pipeline/self_correction/layer.py` |
| 6 — Answer Generation | ✅ Implemented | `pipeline/answer_generation/layer.py` |

## Project structure

```
chat-with-unknown-data/
├── pipeline/
│   ├── __init__.py          ← orchestrator
│   ├── base.py              ← BaseLayer class
│   ├── introspection/
│   ├── enrichment/
│   ├── rag/
│   ├── sql_generation/
│   └── self_correction/
├── api/
│   ├── main.py              ← FastAPI server
│   └── database_manager.py
├── frontend/
│   └── index.html
├── tests/
├── docs/
└── requirements.txt
```
