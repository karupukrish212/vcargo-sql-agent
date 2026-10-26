# Fleet data assistant: API for the frontend

Base URL: `http://<server>:8000` (local: `http://127.0.0.1:8000`).
Interactive docs with "Try it out": **`/docs`**. OpenAPI schema: `/openapi.json`.

If the server sets `API_KEY`, send it on every request as the header `X-API-Key`.

## The flow

```
user types question ──► POST /api/ask ──► show SQL, table, chart
                                          ├─ "Download CSV" ──► GET  /api/results/{id}/csv
                                          └─ "Were the results correct?"
                                               Yes ──► POST /api/results/{id}/feedback {correct: true}
                                               No  ──► POST /api/results/{id}/feedback {correct: false, comment}
                                                       then offer a correction:
                                                       ├─ edit the SQL    ──► POST /api/results/{id}/run-sql {sql}
                                                       └─ describe problem ──► POST /api/results/{id}/fix {comment}
                                                       both return a NEW result (new id) to show,
                                                       and ask "Were the results correct?" again
```

When the user says **Yes** to a corrected result, the **original question** is trained
with the **corrected SQL**, so the assistant answers it correctly next time.

A result `id` stays valid for 60 minutes (`RESULT_CACHE_MINUTES`). After that, CSV and
feedback return 404 and the user should ask again.

## POST /api/ask

Answering takes about 5-15 seconds (the model runs locally), so show a loading state.

Request:
```json
{ "question": "Which vehicle used the most fuel last month?", "chart": true }
```
`chart` is optional (default `true`).

Response `200`:
```json
{
  "id": "cab3928db22747d7ace2d41ea4f9fa1f",
  "question": "Which vehicle used the most fuel last month?",
  "sql": "SELECT v.vehiclenumber, SUM(f.quantity) AS litres ...",
  "columns": ["vehiclenumber", "litres", "fuel_cost"],
  "rows": [{ "vehiclenumber": "TN-09-AB-0909", "litres": 30.0, "fuel_cost": 3300.0 }],
  "row_count": 1,
  "truncated": false,
  "chart": null,
  "display": "table"
}
```
- **`display` tells the frontend what to show:**

  | `display` | When | Show |
  |---|---|---|
  | `"number"` | one row, one column (e.g. total profit) | the value as a big number (KPI card) |
  | `"chart"` | several rows with a label and numbers | the chart, with the table below it |
  | `"table"` | anything else (one row with several columns, text only) | the table |
- `rows` are objects keyed by column, in `columns` order. Dates are ISO strings, money is a number.
- `truncated: true` means the result hit the row limit (5000); suggest a narrower question.
- `chart` is a Plotly figure `{ data, layout }`, or `null` when a chart doesn't help (a single value, or no numbers).

Errors:

| Status | When | Body |
|---|---|---|
| 400 | Query blocked (confidential column, non-business table, not a SELECT) | `{"detail": {"message": "...", "sql": "..."}}` |
| 422 | The model couldn't produce working SQL, or answered in text | `{"detail": {"message": "...", "sql": "..." or null}}` |
| 401 | Missing/wrong `X-API-Key` | `{"detail": "..."}` |

Show `detail.message` to the user.

## GET /api/results/{id}/csv

Returns `text/csv` with a filename in `Content-Disposition`. It's UTF-8 with BOM, so it opens correctly in Excel.

## POST /api/results/{id}/feedback

```json
{ "correct": true }
{ "correct": false, "comment": "should only include diesel" }
```
- `correct: true` → `{"status": "trained", "training_id": "..."}`. The question and SQL are saved
  as an example and used for future questions. Only show "Yes" after the user has seen the result.
- `correct: false` → `{"status": "logged"}`. Saved to `feedback/wrong_answers.jsonl` for the
  maintainers to fix with documentation or examples.

## Correcting a wrong answer

Both return the same shape as `/api/ask`, with a **new `id`** and the same `question`.
Errors are the same as `/api/ask` (400 blocked, 422 failed), with `detail.message` and `detail.sql`.

### POST /api/results/{id}/run-sql: the user edits the SQL

For people who know SQL (like editing the SQL in the old Flask UI).
```json
{ "sql": "SELECT tripid, CONCAT(source, ' -> ', destination) AS route, profit FROM trip WHERE ..." }
```
The query goes through the same safety checks as generated SQL: SELECT only, business
tables only, no confidential columns.

### POST /api/results/{id}/fix: the user describes what is wrong

For everyone else. The model rewrites the SQL using the comment.
```json
{ "comment": "I want one row per trip with its route, not a single total" }
```
Takes about 5-15 seconds, like `/api/ask`.

## Admin endpoints

- `GET /api/training-data?type=sql`: list saved examples (`type` = `sql`, `ddl` or `documentation`)
- `DELETE /api/training-data/{id}`: remove a wrong example (e.g. "Yes" clicked by mistake)
- `GET /api/health`: `{"database": "ok", "llm": "ok"}`, or 503 with the failing part

## React example

```bash
npm install react-plotly.js plotly.js-dist-min
```

```jsx
import { useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);
const API = "http://127.0.0.1:8000";
const headers = { "Content-Type": "application/json" /*, "X-API-Key": "..." */ };

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);

  async function ask() {
    setLoading(true); setError(null); setResult(null); setFeedbackSent(false);
    const res = await fetch(`${API}/api/ask`, { method: "POST", headers, body: JSON.stringify({ question }) });
    const body = await res.json();
    setLoading(false);
    if (!res.ok) return setError(body.detail?.message ?? body.detail);
    setResult(body);
  }

  async function downloadCsv() {
    // fetch + blob (instead of a plain link) so the X-API-Key header can be sent
    const res = await fetch(`${API}/api/results/${result.id}/csv`, { headers });
    const name = res.headers.get("Content-Disposition")?.match(/filename="(.+)"/)?.[1] ?? "result.csv";
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: name }).click();
    URL.revokeObjectURL(url);
  }

  async function sendFeedback(correct) {
    await fetch(`${API}/api/results/${result.id}/feedback`, {
      method: "POST", headers, body: JSON.stringify({ correct }),
    });
    setFeedbackSent(correct ? "trained" : "wrong");
  }

  // Wrong answer: run the user's edited SQL, or let the model fix it from a comment.
  // Either way we get a new result and ask "Were the results correct?" again.
  async function correct(path, payload) {
    setLoading(true); setError(null);
    const res = await fetch(`${API}/api/results/${result.id}/${path}`, {
      method: "POST", headers, body: JSON.stringify(payload),
    });
    const body = await res.json();
    setLoading(false);
    if (!res.ok) return setError(body.detail?.message ?? body.detail);
    setResult(body);
    setFeedbackSent(false);
  }

  return (
    <div>
      <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} />
      <button onClick={ask} disabled={loading}>{loading ? "Thinking..." : "Ask"}</button>
      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <pre>{result.sql}</pre>

          {result.display === "number" && <BigNumber result={result} />}

          {result.display === "chart" && (
            <Plot data={result.chart.data} layout={{ ...result.chart.layout, autosize: true }}
                  useResizeHandler style={{ width: "100%", height: 400 }} />
          )}

          {result.display !== "number" && <ResultTable result={result} />}

          <button onClick={downloadCsv}>Download CSV</button>

          {!feedbackSent && (
            <p>
              Were the results correct?{" "}
              <button onClick={() => sendFeedback(true)}>Yes, train as Question-SQL pair</button>
              <button onClick={() => sendFeedback(false)}>No</button>
            </p>
          )}
          {feedbackSent === "trained" && <p>Thanks! Saved as an example.</p>}
          {feedbackSent === "wrong" && (
            <CorrectionPanel sql={result.sql} loading={loading}
              onRunSql={(sql) => correct("run-sql", { sql })}
              onFix={(comment) => correct("fix", { comment })} />
          )}
        </>
      )}
    </div>
  );
}

// One value, e.g. {"total_profit": 22000} -> "Total profit  ₹22,000"
function BigNumber({ result }) {
  const column = result.columns[0];
  const value = result.rows[0]?.[column];
  const label = column.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  const isMoney = /profit|revenue|cost|amount|price|paid|due|value|expense|toll|gst|tax/i.test(column);
  const text = value == null ? "No data"
    : typeof value === "number"
      ? (isMoney ? "₹" : "") + value.toLocaleString("en-IN", { maximumFractionDigits: 2 })
      : String(value);
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{text}</div>
    </div>
  );
}

function CorrectionPanel({ sql, loading, onRunSql, onFix }) {
  const [editedSql, setEditedSql] = useState(sql);
  const [comment, setComment] = useState("");
  return (
    <div className="correction">
      <p>Tell us what's wrong:</p>
      <input placeholder="e.g. show one row per trip with its route"
             value={comment} onChange={(e) => setComment(e.target.value)} />
      <button disabled={loading || comment.trim().length < 3} onClick={() => onFix(comment)}>
        Fix it
      </button>

      <p>Or edit the SQL yourself:</p>
      <textarea rows={8} value={editedSql} onChange={(e) => setEditedSql(e.target.value)} />
      <button disabled={loading} onClick={() => onRunSql(editedSql)}>Run SQL</button>
    </div>
  );
}

function ResultTable({ result }) {
  return (
    <table>
      <thead><tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>
        {result.rows.map((row, i) => (
          <tr key={i}>{result.columns.map((c) => <td key={c}>{row[c]}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}
```
