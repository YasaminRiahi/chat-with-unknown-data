# Conversation with Data

### Bilingual, schema-aware Text-to-SQL for databases the model has never seen

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQL Server](https://img.shields.io/badge/Microsoft-SQL_Server-CC2927?logo=microsoftsqlserver&logoColor=white)](https://www.microsoft.com/sql-server)
[![Tests](https://img.shields.io/badge/tests-62-blue)](tests)

Conversation with Data turns English or Persian questions into safe, read-only
T-SQL, runs them against a previously unseen Microsoft SQL Server database, and
returns a plain-language answer with the most useful table, KPI, or chart.

The system discovers a database at runtime—no schema-specific fine-tuning or
hard-coded business schema is required. It combines schema introspection,
LLM-assisted metadata enrichment, hybrid retrieval, schema linking, execution
feedback, and bounded self-correction in an end-to-end web application.

<p align="center">
  <img src="docs/assets/dashboard.png" alt="Conversation with Data analytics dashboard showing a natural-language query, generated insights, and a time-series chart" width="100%">
</p>

<p align="center"><em>Ask in English or Persian, inspect the generated analysis, and explore the result as a KPI, table, or chart.</em></p>

## Highlights

- **Zero-shot database onboarding:** introspects tables, columns, primary keys,
  foreign keys, and relationships from any connected SQL Server database.
- **English and Persian support:** multilingual BGE-M3 embeddings plus
  SQL Server Unicode literal handling.
- **Hybrid schema retrieval:** combines dense cosine similarity and BM25 with
  Reciprocal Rank Fusion, deterministic relationship rules, and LLM schema linking.
- **Safe execution:** accepts one read-only `SELECT`/CTE statement and blocks
  DML, DDL, administrative commands, `SELECT INTO`, and multiple statements.
- **Self-correcting SQL:** uses database errors and empty-result feedback to repair
  invalid SQL or high-confidence misspelled text values.
- **Interactive analytics:** displays answers as KPIs, tables, bar charts, or line
  charts and exports results as CSV or PNG.
- **Efficient repeat use:** caches enriched metadata and embeddings by schema
  fingerprint, rebuilding only changed artifacts.
- **Auditable model usage:** records request metadata, latency, response status,
  and provider token usage as JSONL.

## Evaluation

The checked-in evaluation run contains **200 bilingual questions** (104 English,
96 Persian) against a previously unseen accounting database. Predictions are
scored by comparing the generated query result with the reference query result,
not by requiring an exact SQL string match.

| Metric | Result |
|---|---:|
| Final execution accuracy | **95.5%** |
| Initial execution accuracy | 90.5% |
| Valid SQL rate | **100%** |
| Table recall | 97.0% |
| Column recall | 97.1% |
| English execution accuracy | 97.1% |
| Persian execution accuracy | 93.8% |
| Typo recovery | **10 / 10** |

Results are from the reproducible `v1` run and are specific to its dataset,
database, model, and configuration. See the [evaluation summary](evaluation/runs/v1/summary.json),
[interactive report](evaluation/runs/v1/report.html), and
[evaluation methodology](evaluation/README.md) for details.

## Architecture

<p align="center">
  <img src="docs/assets/architecture.png" alt="Architecture of the seven-stage bilingual Text-to-SQL pipeline, from schema introspection through answer visualization" width="100%">
</p>

The seven implementation layers are intentionally isolated behind a shared base
interface, which keeps retrieval, correction, answer generation, and presentation
independently testable.

## Technical report

For a formal treatment of the problem formulation, layer-by-layer methodology,
theoretical foundations, evaluation protocol, threats to validity, and research
extensions, read the [academic technical report](docs/technical-report.md).

## Tech stack

| Area | Technology |
|---|---|
| API and orchestration | Python 3.12, FastAPI, LangChain |
| Database | Microsoft SQL Server, SQLAlchemy, pyodbc |
| Language model | Groq (default: `openai/gpt-oss-120b`) |
| Embeddings | Ollama with `bge-m3` |
| Retrieval | Dense cosine search, BM25, Reciprocal Rank Fusion |
| Frontend | HTML, CSS, JavaScript, Chart.js |
| Deployment | Docker Compose, Nginx |
| Quality | pytest, bilingual execution-based benchmark |

## Quick start with Docker

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose
- [Ollama](https://ollama.com/) running on the host
- A [Groq API key](https://console.groq.com/keys)
- Network access to a Microsoft SQL Server instance

```bash
git clone https://github.com/YasaminRiahi/chat-with-unknown-data.git
cd chat-with-unknown-data

ollama pull bge-m3
cp .env.example .env
```

On Windows PowerShell, use `Copy-Item .env.example .env` instead of `cp`. Add
your key to `.env`:

```dotenv
GROQ_API_KEY=your_groq_api_key
```

Start the application:

```bash
docker compose up --build -d
```

Open <http://localhost:25796>, select **Add database**, and provide a SQLAlchemy
SQL Server connection string. For a SQL Server running on the Docker host, use
`host.docker.internal` rather than `localhost`:

```text
mssql+pyodbc://USER:PASSWORD@host.docker.internal/DATABASE?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
```

Stop the application with `docker compose down`. For additional Docker and FRP
notes, see the [Docker and FRP guide](DOCKER_GUIDE.md).

## Local development

Local execution requires Python 3.12 and Microsoft ODBC Driver 18 for SQL Server.

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
ollama pull bge-m3
cp .env.example .env
```

After setting `GROQ_API_KEY` in `.env`, run the API and frontend in separate
terminals:

```bash
uvicorn api.main:app --reload --port 8000
python -m http.server 5500 -d frontend
```

Open <http://localhost:5500>. Interactive API documentation is available at
<http://localhost:8000/docs>.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | required | Groq authentication key |
| `CHAT_MODEL` | `openai/gpt-oss-120b` | Chat, SQL, and answer model |
| `EMBEDDING_MODEL` | `bge-m3` | Ollama embedding model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `LLM_ENRICHMENT_ENABLED` | `true` | Generate conservative schema descriptions |
| `ENRICHMENT_BATCH_SIZE` | `12` | Metadata items per enrichment batch |
| `SCHEMA_LINKING_ENABLED` | `true` | Enable LLM-assisted final table selection |
| `CORS_ALLOWED_ORIGINS` | local UI origins | Comma-separated browser origins |
| `MODEL_LOG_PATH` | `logs/model_calls.jsonl` | Model audit log location |
| `ENRICHMENT_CACHE_DIR` | `.cache/enrichment` | Enriched metadata cache |
| `EMBEDDING_CACHE_DIR` | `.cache/embeddings` | Embedding cache |

## How a question is processed

1. **Introspection** discovers authoritative database structure and relationships.
2. **Enrichment** adds conservative bilingual descriptions and caches them by DDL fingerprint.
3. **Retrieval** ranks tables and columns with dense and lexical search, expands relationships,
   and validates an LLM-selected schema subset.
4. **SQL generation** creates schema-grounded, Microsoft SQL Server-compatible T-SQL.
5. **Self-correction** validates read-only safety, executes the query, and performs bounded
   correction from execution or empty-result feedback.
6. **Answer generation** explains the returned rows in the user's language.
7. **Visualization** chooses a KPI, table, bar chart, or line chart without changing the data.

Structural questions such as “How many tables are there?” bypass embeddings and
the LLM and are answered directly from introspected metadata.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Service and model status |
| `GET` | `/databases` | List connected databases and the active selection |
| `POST` | `/databases` | Validate and add a SQL Server connection |
| `POST` | `/databases/activate` | Select the database for the current session |
| `DELETE` | `/databases/{name}` | Remove a database connection |
| `POST` | `/chat` | Run a natural-language question through the pipeline |
| `DELETE` | `/chat/history` | Clear the current session history |

Browser clients receive an isolated context through the `X-Session-ID` header.
Database registrations are in-memory and must be added again after a server restart.

## Tests

The suite currently contains 62 tests across retrieval, SQL safety and generation,
self-correction, evaluation, database management, answer generation, and visualization.

```bash
python -m pip install pytest
python -m pytest -q
```

The benchmark runner supports checkpoints, resume, token budgets, language/category
filters, per-question diagnostics, and standalone HTML reports. Its usage is documented
in [`evaluation/README.md`](evaluation/README.md).

## Project structure

```text
chat-with-unknown-data/
|-- api/                 # FastAPI routes, sessions, configuration, model logging
|-- pipeline/            # Seven-stage Text-to-SQL pipeline
|-- frontend/            # Responsive analytics UI
|-- evaluation/          # Dataset, benchmark runner, reports, and v1 results
|-- tests/                # Unit and integration-style tests
|-- docs/                 # Architecture and research documentation
|-- docker/               # Nginx configuration
|-- compose.yaml
|-- Dockerfile
`-- requirements.txt
```

## Security and privacy

Application-level SQL validation is defense in depth, not a replacement for database
permissions. Use a dedicated SQL Server login with read-only access to only the schemas
the application needs. Keep `.env`, `logs/`, and `.cache/` private: model logs and cached
artifacts can contain schema names, user questions, query results, and other sensitive
business information. Connection strings are intentionally excluded from API responses.

---

Built as an exploration of reliable, multilingual Text-to-SQL over large, unfamiliar
enterprise schemas.
