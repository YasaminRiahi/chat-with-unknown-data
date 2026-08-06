"""
api/main.py
===========
FastAPI server — chat + database management endpoints.

Run:
  pip install fastapi uvicorn
  uvicorn api.main:app --reload --port 8000

Or from project root:
  python -m uvicorn api.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from api.database_manager import DatabaseManager
from api.config import Settings
from api.model_logging import (
    LoggedChatModel,
    LoggedOllamaEmbeddings,
    ModelCallLogger,
)
from pipeline import Pipeline


# ── Config ────────────────────────────────────────────────────────────────────

settings = Settings.from_env()


# ── App setup ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(
        f"Starting - model: {settings.chat_model} | "
        f"embeddings: {settings.embedding_model}"
    )
    yield
    print("Shutting down.")

app = FastAPI(title="Conversation with Data", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten this in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Core singletons ───────────────────────────────────────────────────────────

model_call_logger = ModelCallLogger(settings.model_log_path)

groq_model = ChatGroq(
    model=settings.chat_model,
    api_key=settings.groq_api_key,
    temperature=0.1,
)
llm = LoggedChatModel(groq_model, model_call_logger)

embeddings = LoggedOllamaEmbeddings(
    model=settings.embedding_model,
    base_url=settings.ollama_base_url,
).configure_logging(model_call_logger)

db_manager = DatabaseManager()
pipeline = Pipeline(
    llm,
    embeddings,
    db_manager,
    enrichment_cache_dir=settings.enrichment_cache_dir,
    embedding_cache_dir=settings.embedding_cache_dir,
    llm_enrichment_enabled=settings.llm_enrichment_enabled,
    enrichment_batch_size=settings.enrichment_batch_size,
)

# ── Session state (single session, in-memory) ─────────────────────────────────
# TODO: replace with Redis or DB-backed sessions for multi-user support

chat_history: list[dict] = []
active_db: str | None    = None


# ── Request/response models ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class AddDatabaseRequest(BaseModel):
    name:              str
    type:              str = "sqlite"
    connection_string: str

class ActivateRequest(BaseModel):
    name: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    db_list = db_manager.list_databases()
    db_info = "\n".join(f"  - {n}" for n in db_list) if db_list else "  (none connected)"
    return f"""You are a helpful data assistant for the "Conversation with Data" system.
You help users query databases using plain English — no SQL knowledge required.

Connected databases:
{db_info}

Active database: {active_db or "none selected"}

If no database is selected and the user asks a data question, ask them to pick one.
Be concise and friendly.
"""

def detect_intent(message: str) -> str:
    msg = message.lower()
    if re.fullmatch(r"\s*(hi|hello|hey|سلام|درود)[!.?\s]*", msg):
        return "greeting"
    if any(k in msg for k in ["what database", "which database", "list database",
                               "what db", "connected db", "available db",
                               "چه دیتابیس", "چه پایگاه"]):
        return "list_databases"
    return "query"

def handle_list_databases() -> str:
    dbs = db_manager.list_databases()
    if not dbs:
        return "No databases connected. Add one using the sidebar."
    lines = "\n".join(f"• **{n}** ({db_manager.get_info(n)['type']})" for n in dbs)
    active = f"\n\nCurrently active: **{active_db}**" if active_db else ""
    return f"Connected databases:\n\n{lines}{active}"

def run_chat(user_message: str) -> str:
    global active_db

    intent = detect_intent(user_message)

    if intent == "greeting":
        return "Hi! Ask me a question about your connected database."

    if intent == "list_databases":
        return handle_list_databases()

    # Auto-select if only one DB connected
    if not active_db:
        dbs = db_manager.list_databases()
        if len(dbs) == 1:
            active_db = dbs[0]
        elif len(dbs) > 1:
            names = ", ".join(f"**{d}**" for d in dbs)
            return f"Multiple databases connected: {names}. Which one should I query?"

    # Run pipeline if a DB is active
    if active_db:
        metadata_answer = pipeline.answer_metadata_question(user_message, active_db)
        if metadata_answer is not None:
            return metadata_answer
        result = pipeline.run(user_message, active_db)
        if result["success"]:
            return result["answer"]
        else:
            return f"I couldn't process that request: {result.get('error')}"

    # Build message list for LLM
    messages = [SystemMessage(content=build_system_prompt())]
    for turn in chat_history[-10:]:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=user_message))

    response = llm.invoke(messages)
    return response.content


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": settings.chat_model,
        "embedding_model": settings.embedding_model,
    }

@app.get("/databases")
def list_databases():
    dbs = [{"name": n, **db_manager.get_info(n)} for n in db_manager.list_databases()]
    return {"databases": dbs, "active": active_db}

@app.post("/databases")
def add_database(req: AddDatabaseRequest):
    global active_db
    try:
        db_manager.add_database(req.name, req.type, req.connection_string)
        pipeline.clear_cache(req.name)
        if not active_db:
            active_db = req.name
        return {"success": True, "active": active_db}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/databases/activate")
def activate_database(req: ActivateRequest):
    global active_db
    if req.name not in db_manager.list_databases():
        raise HTTPException(status_code=404, detail=f"'{req.name}' not found")
    active_db = req.name
    return {"success": True, "active": active_db}

@app.delete("/databases/{name}")
def remove_database(name: str):
    global active_db
    try:
        db_manager.remove_database(name)
        pipeline.clear_cache(name)
        if active_db == name:
            remaining = db_manager.list_databases()
            active_db = remaining[0] if remaining else None
        return {"success": True, "active": active_db}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/chat")
def chat(req: ChatRequest):
    global chat_history
    msg = req.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Empty message")

    chat_history.append({"role": "user", "content": msg})
    reply = run_chat(msg)
    chat_history.append({"role": "assistant", "content": reply})

    return {"reply": reply, "active_db": active_db}

@app.delete("/chat/history")
def clear_history():
    global chat_history
    chat_history = []
    return {"success": True}
