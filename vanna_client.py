"""Builds the Vanna instance: local Ollama LLM + local ChromaDB memory + guarded MySQL."""
from vanna.chromadb import ChromaDB_VectorStore
from vanna.ollama import Ollama

import settings
from safe_sql import make_run_sql


class LocalVanna(ChromaDB_VectorStore, Ollama):
    def __init__(self, config: dict):
        ChromaDB_VectorStore.__init__(self, config=config)
        Ollama.__init__(self, config=config)


def build_vanna() -> LocalVanna:
    vn = LocalVanna({
        "path": settings.VECTOR_STORE_PATH,
        "n_results": settings.RETRIEVAL_RESULTS,
        "model": settings.OLLAMA_MODEL,
        "ollama_host": settings.OLLAMA_HOST,
        "ollama_timeout": settings.OLLAMA_TIMEOUT_SECONDS,
        "options": {"num_ctx": settings.OLLAMA_NUM_CTX, "temperature": 0},
        "dialect": "MySQL 8",
        # Prompt budget (approx. tokens) for schema + docs + examples; leave room for the answer
        "max_tokens": int(settings.OLLAMA_NUM_CTX * 0.75),
    })
    vn.run_sql = make_run_sql(set(settings.load_business_tables()), settings.load_hidden_columns())
    vn.run_sql_is_set = True
    return vn
