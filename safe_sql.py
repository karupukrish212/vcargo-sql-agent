"""Read-only, time-limited, row-capped SQL execution against MySQL.

These checks are a second line of defence. The first is the database itself:
connect with a MySQL user that only has SELECT on the business tables.
"""
import logging
import re

import pandas as pd
import pymysql
import sqlparse

import settings

log = logging.getLogger(__name__)

# Things that are dangerous or side-effecting even inside a SELECT
_FORBIDDEN = re.compile(
    r"\bINTO\s+(OUTFILE|DUMPFILE)\b|\bINTO\s+@|\bFOR\s+(UPDATE|SHARE)\b|\bLOCK\s+IN\s+SHARE\s+MODE\b"
    r"|\b(SLEEP|BENCHMARK|GET_LOCK|LOAD_FILE)\s*\(",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:FROM|JOIN)\s+([`\w.]+)", re.IGNORECASE)
_CTE_NAME = re.compile(r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)`?(\w+)`?\s+AS\s*\(", re.IGNORECASE)
# SELECT *, SELECT DISTINCT *, ", *" and "alias.*" -- but not COUNT(*) or a * b
_STAR_SELECT = re.compile(r"(?:\bSELECT\s+(?:DISTINCT\s+)?|,\s*|\.)\*", re.IGNORECASE)


class UnsafeSQLError(ValueError):
    pass


def check_read_only(sql: str, allowed_tables: set[str] | None = None,
                    hidden_columns: dict[str, set[str]] | None = None) -> str:
    """Return the cleaned statement, or raise UnsafeSQLError."""
    cleaned = sqlparse.format(sql, strip_comments=True).strip().rstrip(";").strip()
    statements = [s for s in sqlparse.parse(cleaned) if s.value.strip()]
    if len(statements) != 1:
        raise UnsafeSQLError("Only a single SQL statement is allowed.")

    first_word = cleaned.lstrip("( \n\t").split(None, 1)[0].upper() if cleaned else ""
    if first_word not in ("SELECT", "WITH") or statements[0].get_type() not in ("SELECT", "UNKNOWN"):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    if _FORBIDDEN.search(cleaned):
        raise UnsafeSQLError("This query uses a construct that is not allowed (locking, file or variable output, sleep).")

    referenced = set()
    if allowed_tables is not None:
        allowed = {t.lower() for t in allowed_tables}
        ctes = {m.lower() for m in _CTE_NAME.findall(cleaned)}
        for ref in _TABLE_REF.findall(cleaned):
            parts = ref.replace("`", "").lower().split(".")
            if len(parts) == 2 and parts[0] != settings.MYSQL_DATABASE.lower():
                raise UnsafeSQLError(f"Queries may only use the {settings.MYSQL_DATABASE} database (found {ref}).")
            table = parts[-1]
            if table not in allowed and table not in ctes:
                raise UnsafeSQLError(f"Table {table} is not one of the business tables this assistant may query.")
            referenced.add(table)

    if hidden_columns:
        for table, columns in hidden_columns.items():
            for column in columns:
                if re.search(rf"\b{re.escape(column)}\b", cleaned, re.IGNORECASE):
                    raise UnsafeSQLError(f"Column {column} is confidential and cannot be queried.")
        restricted = sorted(referenced & hidden_columns.keys())
        if restricted and _STAR_SELECT.search(cleaned):
            raise UnsafeSQLError(
                f"SELECT * is not allowed on {', '.join(restricted)}; list the needed columns explicitly.")
    return cleaned


def _connect():
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=settings.QUERY_TIMEOUT_SECONDS + 5,
        autocommit=False,
    )


def _execute_read_only(sql: str, max_rows: int):
    # A fresh connection per query keeps this safe under Flask's threaded server
    conn = _connect()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("SET SESSION MAX_EXECUTION_TIME = %s", (settings.QUERY_TIMEOUT_SECONDS * 1000,))
            except pymysql.Error:
                # MariaDB and MySQL < 5.7.8 don't have it; read_timeout still applies
                pass
            cur.execute("START TRANSACTION READ ONLY")
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(max_rows + 1)
        conn.rollback()
    finally:
        conn.close()
    return columns, rows


def make_run_sql(allowed_tables: set[str], hidden_columns: dict[str, set[str]]):
    """Build the run_sql function Vanna calls for every generated query."""

    def run_sql(sql: str) -> pd.DataFrame:
        query = check_read_only(sql, allowed_tables, hidden_columns)
        columns, rows = _execute_read_only(query, settings.MAX_RESULT_ROWS)
        df = pd.DataFrame(list(rows[: settings.MAX_RESULT_ROWS]), columns=columns)
        if len(rows) > settings.MAX_RESULT_ROWS:
            log.warning("Result truncated to %d rows", settings.MAX_RESULT_ROWS)
            df.attrs["truncated"] = True
        return df

    return run_sql


def explain(sql: str, allowed_tables: set[str], hidden_columns: dict[str, set[str]]) -> None:
    """Check that a query is safe and valid against the live schema without running it."""
    query = check_read_only(sql, allowed_tables, hidden_columns)
    _execute_read_only("EXPLAIN " + query, max_rows=1000)


def fetch_rows(sql: str, params=None) -> list[tuple]:
    """Trusted metadata queries used by training (not for user/LLM SQL)."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    finally:
        conn.close()
