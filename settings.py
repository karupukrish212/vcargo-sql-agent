"""All configuration comes from environment variables (loaded from .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required setting {name} (see .env.example)")
    return value


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# MySQL -- use a read-only user that only has SELECT on the business tables
MYSQL_HOST = _required("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = _required("MYSQL_DATABASE")
MYSQL_USER = _required("MYSQL_USER")
MYSQL_PASSWORD = _required("MYSQL_PASSWORD")

# Query guard rails
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))
MAX_RESULT_ROWS = int(os.getenv("MAX_RESULT_ROWS", "5000"))

# Local LLM (Ollama)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "240"))

# Vector store (Vanna's training memory)
VECTOR_STORE_PATH = os.getenv("VECTOR_STORE_PATH", str(ROOT / "vector_store"))
RETRIEVAL_RESULTS = int(os.getenv("RETRIEVAL_RESULTS", "10"))

# Training inputs
TABLES_FILE = ROOT / "config" / "tables.txt"
HIDDEN_COLUMNS_FILE = ROOT / "config" / "hidden_columns.txt"
DOCUMENTATION_FILE = ROOT / "training" / "documentation.md"
EXAMPLES_FILE = ROOT / "training" / "examples.sql"

# Web app
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8084"))
APP_TITLE = os.getenv("APP_TITLE", "Ask the database")
ALLOW_LLM_TO_SEE_DATA = _bool("ALLOW_LLM_TO_SEE_DATA", False)
SHOW_TRAINING_DATA = _bool("SHOW_TRAINING_DATA", True)

# REST API for the React frontend
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")  # empty = no key required
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]
RESULT_CACHE_MINUTES = int(os.getenv("RESULT_CACHE_MINUTES", "60"))
FEEDBACK_LOG = ROOT / "feedback" / "wrong_answers.jsonl"


def _read_list(path: Path) -> list[str]:
    """One entry per line, '#' starts a comment."""
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.append(entry)
    return entries


def load_business_tables() -> list[str]:
    """Table allowlist from config/tables.txt."""
    tables = _read_list(TABLES_FILE)
    if not tables:
        raise RuntimeError(f"{TABLES_FILE} is missing or has no tables listed")
    return tables


def load_hidden_columns() -> dict[str, set[str]]:
    """{table: {column, ...}} from config/hidden_columns.txt, all lower-case."""
    hidden: dict[str, set[str]] = {}
    for entry in _read_list(HIDDEN_COLUMNS_FILE):
        table, _, column = entry.lower().partition(".")
        if not column:
            raise RuntimeError(f"{HIDDEN_COLUMNS_FILE.name}: '{entry}' must be table.column")
        hidden.setdefault(table, set()).add(column)
    return hidden
