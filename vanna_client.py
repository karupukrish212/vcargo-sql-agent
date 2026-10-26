"""Builds the Vanna instance: LLM (Ollama or Groq) + local ChromaDB memory + guarded MySQL.

LLM_PROVIDER in .env picks one per installation. With "ollama", the Groq client is never
imported or called, so an offline client sends nothing outside its network.
"""
import logging

from vanna.chromadb import ChromaDB_VectorStore

import settings
from safe_sql import make_run_sql

log = logging.getLogger(__name__)


def _vanna_class():
    if settings.LLM_PROVIDER == "groq":
        from openai import OpenAI
        from vanna.openai import OpenAI_Chat

        class GroqVanna(ChromaDB_VectorStore, OpenAI_Chat):
            def __init__(self, config: dict):
                ChromaDB_VectorStore.__init__(self, config=config)
                client = OpenAI(api_key=settings.GROQ_API_KEY, base_url=settings.GROQ_BASE_URL,
                                timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=2)
                OpenAI_Chat.__init__(self, client=client, config=config)

            def submit_prompt(self, prompt, **kwargs) -> str:
                # Own call instead of OpenAI_Chat's so reasoning models (gpt-oss) get reasoning_effort
                extra = {"reasoning_effort": settings.GROQ_REASONING_EFFORT} if settings.GROQ_REASONING_EFFORT else {}
                response = self.client.chat.completions.create(
                    model=settings.GROQ_MODEL, messages=prompt, temperature=0, **extra)
                return response.choices[0].message.content

            def llm_health(self):
                self.client.models.retrieve(settings.GROQ_MODEL)

        return GroqVanna, {"model": settings.GROQ_MODEL, "temperature": 0}

    from vanna.ollama import Ollama

    class OllamaVanna(ChromaDB_VectorStore, Ollama):
        def __init__(self, config: dict):
            ChromaDB_VectorStore.__init__(self, config=config)
            Ollama.__init__(self, config=config)

        def llm_health(self):
            self.ollama_client.show(self.model)

    return OllamaVanna, {
        "model": settings.OLLAMA_MODEL,
        "ollama_host": settings.OLLAMA_HOST,
        "ollama_timeout": settings.OLLAMA_TIMEOUT_SECONDS,
        "options": {"num_ctx": settings.OLLAMA_NUM_CTX, "temperature": 0},
    }


def build_vanna():
    cls, llm_config = _vanna_class()
    vn = cls({
        "path": settings.VECTOR_STORE_PATH,
        "n_results": settings.RETRIEVAL_RESULTS,
        "dialect": "MySQL 8",
        # Prompt budget (approx. tokens) for schema + docs + examples; leave room for the answer
        "max_tokens": int(settings.OLLAMA_NUM_CTX * 0.75),
        **llm_config,
    })
    vn.run_sql = make_run_sql(set(settings.load_business_tables()), settings.load_hidden_columns())
    vn.run_sql_is_set = True
    if settings.LLM_PROVIDER == "groq":
        log.warning("LLM: Groq %s (cloud). Schema, business rules, examples and questions are sent to Groq.",
                    settings.GROQ_MODEL)
    else:
        log.warning("LLM: Ollama %s at %s (offline). Nothing is sent outside this network.",
                    settings.OLLAMA_MODEL, settings.OLLAMA_HOST)
    return vn
