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
    reranker_enabled=settings.reranker_enabled,
    reranker_model=settings.reranker_model,
    schema_linking_enabled=settings.schema_linking_enabled,
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

def is_data_mutation_request(message: str) -> bool:
    mutation_words = (
        r"insert|update|delete|merge|drop|alter|truncate|"
        r"\u0627\u0636\u0627\u0641\u0647|"
        r"\u0627\u06cc\u062c\u0627\u062f|"
        r"\u0628\u0633\u0627\u0632|"
        r"\u0628\u0633\u0627\u0632\u06cc\u062f|"
        r"\u0648\u06cc\u0631\u0627\u06cc\u0634|"
        r"\u062a\u063a\u06cc\u06cc\u0631|"
        r"\u062d\u0630\u0641|"
        r"\u067e\u0627\u06a9"
    )
    data_words = (
        r"record|row|entry|table|database|cost\s*center|voucher|receipt|"
        r"\u0631\u06a9\u0648\u0631\u062f|"
        r"\u0631\u062f\u06cc\u0641|"
        r"\u062c\u062f\u0648\u0644|"
        r"\u062f\u06cc\u062a\u0627\u0628\u06cc\u0633|"
        r"\u067e\u0627\u06cc\u06af\u0627\u0647|"
        r"\u0645\u0631\u06a9\u0632\s*\u0647\u0632\u06cc\u0646\u0647|"
        r"\u0633\u0646\u062f|"
        r"\u0631\u0633\u06cc\u062f"
    )
    field_words = (
        r"type|code|title|name|number|date|"
        r"\u0646\u0648\u0639|"
        r"\u06a9\u062f|"
        r"\u0639\u0646\u0648\u0627\u0646|"
        r"\u0646\u0627\u0645|"
        r"\u0634\u0645\u0627\u0631\u0647|"
        r"\u062a\u0627\u0631\u06cc\u062e"
    )

    direct_dml = re.search(
        mutation_words,
        message,
        re.IGNORECASE,
    )
    if direct_dml and re.search(data_words, message, re.IGNORECASE):
        return True

    write_intent = re.search(
        r"(?:\b(add|create|edit|modify|remove)\b|"
        r"\u0627\u0636\u0627\u0641\u0647|\u0627\u06cc\u062c\u0627\u062f|"
        r"\u0648\u06cc\u0631\u0627\u06cc\u0634|\u062a\u063a\u06cc\u06cc\u0631|\u062d\u0630\u0641|"
        r"\u067e\u0627\u06a9).*"
        rf"(?:{data_words})",
        message,
        re.IGNORECASE,
    )
    field_assignment = re.search(
        rf"(?:\bwith\s+(?:type|code|title|name|number|date)\b|(?:{field_words}))",
        message,
        re.IGNORECASE,
    )
    return bool(write_intent and field_assignment)

def is_persian_text(message: str) -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", str(message or "")))

def read_only_message(message: str = "") -> str:
    if is_persian_text(message):
        return (
            "این داشبورد فقط خواندنی است؛ بنابراین نمی‌توانم رکورد جدید اضافه کنم، "
            "داده‌ای را ویرایش کنم یا چیزی را حذف کنم. می‌توانی سؤال‌های تحلیلی "
            "بپرسی، خلاصه بگیری یا رکوردهای موجود را مشاهده کنی."
        )
    return (
        "This dashboard is read-only, so I cannot add, update, or delete "
        "database records. You can ask analytical questions, request summaries, "
        "or view existing records."
    )

def friendly_error_message(error: object, user_message: str = "") -> str:
    """Convert low-level API/SQL errors into user-facing text."""
    raw = str(error or "").strip()
    lowered = raw.lower()

    read_only_error_signals = [
        "only read-only select",
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "background on this error",
        "sqlalche.me",
    ]
    if any(signal in lowered for signal in read_only_error_signals):
        return read_only_message(user_message or raw)

    model_error_signals = [
        "403",
        "forbidden",
        "401",
        "unauthorized",
        "invalid api key",
        "model",
        "rate limit",
        "quota",
        "permission",
    ]
    if any(signal in lowered for signal in model_error_signals):
        return (
            "I could not generate the answer right now because the AI service "
            "is not available or the selected model is not accessible. "
            "Please check the model/API settings or try again in a moment."
        )

    data_error_signals = ["sql", "syntax", "no such table", "no such column", "database"]
    if any(signal in lowered for signal in data_error_signals):
        return (
            "I could not run this data question successfully. "
            "Please try rephrasing it or check that the selected database has the required tables and columns."
        )

    return (
        "I could not process that request right now. "
        "Please try again or rephrase the question."
    )

def run_chat_detailed(user_message: str) -> dict:
    global active_db

    def text_response(reply: str) -> dict:
        return {
            "reply": reply,
            "sql": None,
            "data": None,
            "visualization": None,
        }

    intent = detect_intent(user_message)

    if intent == "greeting":
        return text_response("Hi! Ask me a question about your connected database.")

    if intent == "list_databases":
        return text_response(handle_list_databases())

    # Auto-select if only one DB connected
    if not active_db:
        dbs = db_manager.list_databases()
        if len(dbs) == 1:
            active_db = dbs[0]
        elif len(dbs) > 1:
            names = ", ".join(f"**{d}**" for d in dbs)
            return text_response(
                f"Multiple databases connected: {names}. Which one should I query?"
            )

    # Run pipeline if a DB is active
    if active_db:
        try:
            metadata_answer = pipeline.answer_metadata_question(user_message, active_db)
            if metadata_answer is not None:
                return text_response(metadata_answer)
            result = pipeline.run(user_message, active_db)
            if result["success"]:
                return {
                    "reply": result["answer"],
                    "sql": result["sql"],
                    "data": result["data"],
                    "visualization": result["visualization"],
                }
            else:
                return text_response(friendly_error_message(result.get("error"), user_message))
        except Exception as exc:
            return text_response(friendly_error_message(exc, user_message))

    # Build message list for LLM
    messages = [SystemMessage(content=build_system_prompt())]
    for turn in chat_history[-10:]:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=user_message))

    try:
        response = llm.invoke(messages)
        return text_response(response.content)
    except Exception as exc:
        return text_response(friendly_error_message(exc, user_message))


def run_chat(user_message: str) -> str:
    """Backward-compatible text-only chat helper."""
    return run_chat_detailed(user_message)["reply"]


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
    response = run_chat_detailed(msg)
    reply = response["reply"]
    chat_history.append({"role": "assistant", "content": reply})

    return {**response, "active_db": active_db}

@app.delete("/chat/history")
def clear_history():
    global chat_history
    chat_history = []
    return {"success": True}
