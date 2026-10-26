"""REST API for the React frontend.

    python api.py      then open http://127.0.0.1:8000/docs for interactive docs

Flow for the frontend:
    POST /api/ask                        question -> SQL, rows, chart, result id
    GET  /api/results/{id}/csv           download the result as CSV
    POST /api/results/{id}/feedback      {"correct": true}  -> saved as a training example
                                         {"correct": false} -> logged for review
    Wrong answer? Get a corrected result (new id), then send {"correct": true} for it:
    POST /api/results/{id}/run-sql       {"sql": "..."}     -> run SQL the user edited
    POST /api/results/{id}/fix           {"comment": "..."} -> model rewrites the SQL

Results are cached in memory for RESULT_CACHE_MINUTES, so run a single worker.
"""
import json
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

import pandas as pd
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

import settings
from charts import build_chart
from safe_sql import UnsafeSQLError
from vanna_client import build_vanna

log = logging.getLogger("api")
logging.basicConfig(level=logging.INFO)

vn = build_vanna()


# ---------- result cache ----------

class ResultCache:
    """Recent results by id, so CSV download and feedback don't need the SQL from the client."""

    def __init__(self, ttl_seconds: int, max_items: int = 500):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, item: dict) -> str:
        result_id = uuid.uuid4().hex
        with self._lock:
            self._items[result_id] = {**item, "created": time.time()}
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return result_id

    def get(self, result_id: str) -> dict:
        with self._lock:
            item = self._items.get(result_id)
            if item and time.time() - item["created"] > self.ttl:
                del self._items[result_id]
                item = None
        if not item:
            raise HTTPException(404, "Result not found or expired. Ask the question again.")
        return item


cache = ResultCache(settings.RESULT_CACHE_MINUTES * 60)


# ---------- helpers ----------

def to_json_ready(df: pd.DataFrame) -> pd.DataFrame:
    """MySQL returns Decimal, BIT (bytes) and TIME (timedelta); make them JSON/CSV friendly."""
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_timedelta64_dtype(s):
            out[col] = s.astype(str).str.replace("0 days ", "", regex=False)
            continue
        values = s.dropna()
        if s.dtype != object or values.empty:
            continue
        if all(isinstance(v, Decimal) for v in values):
            out[col] = s.astype(float)
        elif all(isinstance(v, (bytes, bytearray)) for v in values):
            out[col] = s.map(lambda v: None if v is None else int.from_bytes(v, "big"))
    return out


def generate_and_run(question: str) -> tuple[str, pd.DataFrame]:
    """Generate SQL, run it, and on failure give the LLM one chance to fix it (like the Vanna UI)."""
    sql = vn.generate_sql(question, allow_llm_to_see_data=settings.ALLOW_LLM_TO_SEE_DATA)
    if not vn.is_sql_valid(sql):
        raise HTTPException(422, detail={"message": sql, "sql": None})
    try:
        return sql, vn.run_sql(sql)
    except Exception as first_error:
        log.info("Retrying after error: %s", first_error)
        fix_prompt = (
            f"I have an error: {first_error}\n\nHere is the SQL I tried to run: {sql}\n\n"
            f"This is the question I was trying to answer: {question}\n\n"
            "Can you rewrite the SQL to fix the error?"
        )
        fixed_sql = vn.generate_sql(fix_prompt, allow_llm_to_see_data=settings.ALLOW_LLM_TO_SEE_DATA)
        try:
            return fixed_sql, vn.run_sql(fixed_sql)
        except UnsafeSQLError as e:
            raise HTTPException(400, detail={"message": str(e), "sql": fixed_sql})
        except Exception as e:
            raise HTTPException(422, detail={"message": f"The query failed: {e}", "sql": fixed_sql})


def require_api_key(x_api_key: str | None = Header(default=None)):
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(401, "Missing or wrong X-API-Key header")


# ---------- API models ----------

class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000, examples=["Which vehicle used the most fuel last month?"])
    chart: bool = True


class AskResponse(BaseModel):
    id: str = Field(description="Use for CSV download and feedback")
    question: str
    sql: str
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool = Field(description=f"True if the result was cut at MAX_RESULT_ROWS ({settings.MAX_RESULT_ROWS})")
    chart: dict | None = Field(description="Plotly figure {data, layout} for react-plotly.js, or null")
    display: Literal["number", "chart", "table"] = Field(
        description="How to show it: number = one value as a big number, chart = chart + table, table = table only")


class RunSqlRequest(BaseModel):
    sql: str = Field(min_length=6, max_length=20000, description="The corrected SELECT query")
    chart: bool = True


class FixRequest(BaseModel):
    comment: str = Field(min_length=3, max_length=2000, examples=["Only include diesel, not petrol"])
    chart: bool = True


class FeedbackRequest(BaseModel):
    correct: bool
    comment: str | None = Field(default=None, max_length=2000, description="What was wrong (optional)")


class FeedbackResponse(BaseModel):
    status: Literal["trained", "logged"]
    training_id: str | None = None


class TrainingItem(BaseModel):
    id: str
    type: str
    question: str | None
    content: str


# ---------- app ----------

app = FastAPI(title="Fleet data assistant API", version="1.0.0", dependencies=[Depends(require_api_key)])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
    expose_headers=["Content-Disposition"],
)


def build_response(question: str, sql: str, df: pd.DataFrame, with_chart: bool) -> AskResponse:
    """Cache the result (for CSV, feedback and corrections) and shape it for the frontend."""
    df = to_json_ready(df)
    result_id = cache.put({"question": question, "sql": sql, "df": df})
    chart = build_chart(df) if with_chart else None
    if df.shape == (1, 1):
        display = "number"
    elif chart:
        display = "chart"
    else:
        display = "table"
    return AskResponse(
        id=result_id,
        question=question,
        sql=sql,
        columns=[str(c) for c in df.columns],
        rows=json.loads(df.to_json(orient="records", date_format="iso", default_handler=str)),
        row_count=len(df),
        truncated=bool(df.attrs.get("truncated", False)),
        chart=chart,
        display=display,
    )


@app.post("/api/ask", response_model=AskResponse, tags=["ask"])
def ask(req: AskRequest):
    """Turn a question into SQL, run it read-only, and return rows plus a chart."""
    question = req.question.strip()
    sql, df = generate_and_run(question)
    return build_response(question, sql, df, req.chart)


@app.post("/api/results/{result_id}/run-sql", response_model=AskResponse, tags=["correct a wrong answer"])
def run_corrected_sql(result_id: str, req: RunSqlRequest):
    """Run a corrected SQL query for the same question (like editing the SQL in the Flask UI).

    Returns a new result with a new id. If it is right, send feedback {correct: true} for
    that new id to train the original question with this corrected SQL."""
    item = cache.get(result_id)
    sql = req.sql.strip().rstrip(";")
    try:
        df = vn.run_sql(sql)
    except UnsafeSQLError as e:
        raise HTTPException(400, detail={"message": str(e), "sql": sql})
    except Exception as e:
        raise HTTPException(422, detail={"message": f"The query failed: {e}", "sql": sql})
    return build_response(item["question"], sql, df, req.chart)


@app.post("/api/results/{result_id}/fix", response_model=AskResponse, tags=["correct a wrong answer"])
def fix_with_ai(result_id: str, req: FixRequest):
    """Describe what is wrong in plain words and let the model rewrite the SQL.

    Returns a new result with a new id, for the same original question."""
    item = cache.get(result_id)
    prompt = (
        f"Question: {item['question']}\n\n"
        f"This SQL was generated for it, but the user says the result is wrong:\n{item['sql']}\n\n"
        f"What the user says is wrong: {req.comment}\n\n"
        "Rewrite the SQL so it answers the question correctly."
    )
    sql, df = generate_and_run(prompt)
    return build_response(item["question"], sql, df, req.chart)


@app.get("/api/results/{result_id}/csv", tags=["ask"],
         responses={200: {"content": {"text/csv": {}}, "description": "CSV file"}})
def download_csv(result_id: str):
    """The full result as a CSV file (opens correctly in Excel)."""
    item = cache.get(result_id)
    slug = re.sub(r"[^a-z0-9]+", "_", item["question"].lower()).strip("_")[:60] or "result"
    return Response(
        content=item["df"].to_csv(index=False).encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.csv"'},
    )


@app.post("/api/results/{result_id}/feedback", response_model=FeedbackResponse, tags=["ask"])
def feedback(result_id: str, req: FeedbackRequest):
    """'Were the results correct?' Yes trains the question/SQL pair; No logs it for review.

    For a result from /run-sql or /fix, Yes trains the original question with the corrected SQL."""
    item = cache.get(result_id)
    if req.correct:
        training_id = vn.add_question_sql(question=item["question"], sql=item["sql"])
        log.info("Trained from feedback: %s", item["question"])
        return FeedbackResponse(status="trained", training_id=training_id)

    settings.FEEDBACK_LOG.parent.mkdir(exist_ok=True)
    with settings.FEEDBACK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "question": item["question"],
            "sql": item["sql"],
            "comment": req.comment,
        }, ensure_ascii=False) + "\n")
    return FeedbackResponse(status="logged")


@app.get("/api/training-data", response_model=list[TrainingItem], tags=["training"])
def list_training_data(type: Literal["sql", "ddl", "documentation"] | None = None):
    """What the assistant has learned. Filter with ?type=sql to review saved examples."""
    df = vn.get_training_data()
    if type:
        df = df[df["training_data_type"] == type]
    return [
        TrainingItem(id=r.id, type=r.training_data_type,
                     question=r.question if isinstance(r.question, str) else None, content=r.content)
        for r in df.itertuples()
    ]


@app.delete("/api/training-data/{training_id}", tags=["training"])
def delete_training_data(training_id: str):
    """Remove a wrong example (e.g. one saved by mistake with 'Yes')."""
    if not vn.remove_training_data(training_id):
        raise HTTPException(404, "Training item not found")
    return {"deleted": training_id}


@app.get("/api/health", tags=["system"])
def health():
    """Checks the database and the local LLM."""
    status = {}
    try:
        vn.run_sql("SELECT 1 AS ok")
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {e}"
    try:
        vn.ollama_client.show(vn.model)
        status["llm"] = "ok"
    except Exception as e:
        status["llm"] = f"error: {e}"
    if any(v != "ok" for v in status.values()):
        raise HTTPException(503, detail=status)
    return status


if __name__ == "__main__":
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, workers=1)
