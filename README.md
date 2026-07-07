# chat-with-unknown-data

Zero-shot Text-to-SQL on unknown databases.

## Setup

```bash
pip install -r requirements.txt
```

Ollama must be running with both models:
```bash
ollama serve
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

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
| 1 — Introspection  | ✅ Basic | `pipeline/introspection/layer.py` |
| 2 — Enrichment     | ⬜ Pass  | `pipeline/enrichment/layer.py`    |
| 3 — RAG            | ⬜ Pass  | `pipeline/rag/layer.py`           |
| 4 — SQL Generation | ✅ Basic | `pipeline/sql_generation/layer.py`|
| 5 — Self-Correction| ✅ Basic | `pipeline/self_correction/layer.py`|

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
