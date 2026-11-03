# Fleet data assistant: API for the frontend

Base URL: `http://<server>:8001` (local: `http://127.0.0.1:8001`).
Interactive docs with "Try it out": **`/docs`**. OpenAPI schema: `/openapi.json`.

If the server sets `API_KEY`, send it on every request as the header `X-API-Key`.

## The flow

```
user types question ──► POST /api/ask {question, rows: false, answer: true}
                                          │                     show the written answer in the chat (no rows yet)
                                          ├─ "Show table"   ──► GET  /api/results/{id}/table   (only when clicked)
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

A result `id` stays valid for 60 minutes (`RESULT_CACHE_MINUTES`). After that, the answer,
table, CSV and feedback return 404 and the user should ask again.

## POST /api/ask

Answering takes a few seconds (the model is Groq, in the cloud), so show a loading state.

Request (what a chat sends):
```json
{ "question": "Which vehicle used the most fuel last month?", "chart": true, "rows": false, "answer": true, "sql_visible": false }
```
Only `question` is required. `/run-sql` and `/fix` take the same options.

| Option | Default | Effect |
|---|---|---|
| `chart` | `true` | Add a chart when it helps |
| `rows` | `true` | `false`: `"rows": null`; load the table only when the user asks, with `GET /api/results/{id}/table` |
| `answer` | `false` | `true`: add the written answer (`answer`, `answer_source`, see [/answer](#post-apiresultsidanswer)); takes a few seconds more |
| `sql_visible` | `false` | `true`: return the SQL query; `false`: `"sql": null`, also in error details |

Response `200` (for the request above):
```json
{
  "id": "cab3928db22747d7ace2d41ea4f9fa1f",
  "question": "Which vehicle used the most fuel last month?",
  "answer": "The vehicle **TN-09-AB-0909** used the most fuel, with **30** litres costing **₹3,300**.",
  "answer_source": "llm",
  "sql": null,
  "columns": ["vehiclenumber", "litres", "fuel_cost"],
  "rows": null,
  "row_count": 1,
  "truncated": false,
  "chart": null,
  "display": "table"
}
```
- `answer` is Markdown (show it with e.g. `react-markdown`); `null` unless `"answer": true`.
  It never makes the request fail: if the model can't write it, `answer_source` is `"template"`.
- With `"rows": true` (the default), `rows` holds the table, e.g.
  `[{ "vehiclenumber": "TN-09-AB-0909", "litres": 30.0, "fuel_cost": 3300.0 }]`.
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
| 429 | Groq's rate limit was reached (`Retry-After` header when known) | `{"detail": {"message": "...", "sql": null}}` |
| 503 | Groq is unavailable | `{"detail": {"message": "...", "sql": null}}` |
| 401 | Missing/wrong `X-API-Key` | `{"detail": "..."}` |

Show `detail.message` to the user. `detail.sql` is `null` unless the request had `"sql_visible": true`.

## POST /api/results/{id}/answer

The result as a short written answer, like a chat assistant would give. No request body.
The same answer as `"answer": true` on `/api/ask`, but streamed, for a "typing" effect: call
it right after `/api/ask` (and after `/run-sql` or `/fix`) with the new `id`.

The response is **Markdown text** (`text/markdown`), streamed in pieces as it is written:
read it with `res.body` and show the text as it grows. For example:
```
The vehicle **TN-09-AB-0909** used the most fuel last month, with **30 litres** costing **₹3,300**.
```
- The header `X-Answer-Source` says who wrote it:
  - `llm`: the model wrote it from the first `ANSWER_MAX_ROWS` (50) rows. This only happens when
    the server sets `ALLOW_LLM_TO_SEE_DATA=true`, because those rows are sent to Groq.
  - `template`: the server built it from the result without the model (e.g. `**Total profit:** ₹22,000`
    or a list of the first 10 rows). This is used when `ALLOW_LLM_TO_SEE_DATA=false`, and also when the model
    fails or hits its rate limit. Nothing is sent to Groq.
- It always returns 200, except 404 for an expired `id`. Keep a way to see the table as the
  proof behind the answer.
- Amounts are in rupees with Indian grouping (₹1,25,000), dates like `02 Nov 2026`. The answer
  is in the language of the question.
- Only the SQL is trained by "Yes"; the written answer is not stored.

## GET /api/results/{id}/table

The rows of a result, for a "Show table" button. Call it only when the user clicks, like the
CSV download (the result is kept on the server, so nothing has to be sent).

Response `200`:
```json
{
  "id": "cab3928db22747d7ace2d41ea4f9fa1f",
  "columns": ["vehiclenumber", "litres", "fuel_cost"],
  "rows": [{ "vehiclenumber": "TN-09-AB-0909", "litres": 30.0, "fuel_cost": 3300.0 }],
  "row_count": 1,
  "truncated": false
}
```
The same `rows` that `/api/ask` returns without `"rows": false`. 404 when the `id` has expired.

## GET /api/results/{id}/csv

Returns `text/csv` with a filename in `Content-Disposition`. It's UTF-8 with BOM, so it opens correctly in Excel.

## POST /api/results/{id}/feedback

```json
{ "correct": true }
{ "correct": false, "comment": "should only include diesel" }
```
- `correct: true` → `{"status": "trained", "training_id": "..."}`. The question and SQL are saved
  as an example and used for future questions. They are also added to `training/examples.sql`,
  so they are kept on a new installation; an earlier SQL for the same question is replaced.
  Only show "Yes" after the user has seen the result.
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
- `DELETE /api/training-data/{id}`: remove a wrong example (e.g. "Yes" clicked by mistake), also from `training/examples.sql`
- `GET /api/health`: `{"database": "ok", "llm": "ok"}`, or 503 with the failing part

## React example

A chat: each question gets a reply bubble with the written answer (`"answer": true`). The table
(with the chart, and the SQL when `sql_visible` is on) is loaded only when the user clicks
"Show table". `display` is still returned, but in a chat the written answer takes the place of
the big number. For a "typing" effect, call the streaming [/answer](#post-apiresultsidanswer) instead.

```bash
npm install react-markdown react-plotly.js plotly.js-dist-min
```

```jsx
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);
const API = "http://127.0.0.1:8001";
const headers = { "Content-Type": "application/json" /*, "X-API-Key": "..." */ };
// Sent with every ask / run-sql / fix. sql_visible: true for people who should see (and edit) the SQL.
const OPTIONS = { rows: false, answer: true, sql_visible: false };

async function post(path, payload) {
  const res = await fetch(`${API}${path}`, { method: "POST", headers, body: JSON.stringify(payload) });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail?.message ?? body.detail);
  return body;
}

async function downloadCsv(id) {
  // fetch + blob (instead of a plain link) so the X-API-Key header can be sent
  const res = await fetch(`${API}/api/results/${id}/csv`, { headers });
  const name = res.headers.get("Content-Disposition")?.match(/filename="(.+)"/)?.[1] ?? "result.csv";
  const url = URL.createObjectURL(await res.blob());
  Object.assign(document.createElement("a"), { href: url, download: name }).click();
  URL.revokeObjectURL(url);
}

export default function Chat() {
  // { role: "user", text } or { role: "assistant", result, error, feedback, table, tableOpen }
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);

  const update = (i, patch) => setMessages((all) => all.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  // Show a result (with its written answer) in message i. Used for a new question and for
  // corrections (run-sql / fix), which return a new result.
  async function showResult(i, request) {
    setLoading(true);
    let result;
    try {
      result = await request();
    } catch (e) {
      update(i, { error: e.message });
      return;
    } finally {
      setLoading(false);
    }
    update(i, { result, error: null, feedback: null, table: null, tableOpen: false });
  }

  // "Show table": load the rows the first time only, then just show / hide them
  async function toggleTable(i, m) {
    if (m.table) return update(i, { tableOpen: !m.tableOpen });
    const res = await fetch(`${API}/api/results/${m.result.id}/table`, { headers });
    const body = await res.json();
    if (!res.ok) return update(i, { error: body.detail?.message ?? body.detail });
    update(i, { table: body, tableOpen: true });
  }

  function ask() {
    const q = question.trim();
    if (q.length < 3 || loading) return;
    const i = messages.length + 1; // index of the assistant message added below
    setMessages((all) => [...all, { role: "user", text: q }, { role: "assistant" }]);
    setQuestion("");
    showResult(i, () => post("/api/ask", { question: q, ...OPTIONS }));
  }

  return (
    <div className="chat">
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div key={i} className="bubble user">{m.text}</div>
        ) : (
          <AssistantMessage key={i} message={m} loading={loading}
            onToggleTable={() => toggleTable(i, m)}
            onFeedback={async (correct) => {
              await post(`/api/results/${m.result.id}/feedback`, { correct });
              update(i, { feedback: correct ? "trained" : "wrong" });
            }}
            onRunSql={(sql) => showResult(i, () => post(`/api/results/${m.result.id}/run-sql`, { sql, ...OPTIONS }))}
            onFix={(comment) => showResult(i, () => post(`/api/results/${m.result.id}/fix`, { comment, ...OPTIONS }))} />
        )
      )}
      <input value={question} placeholder="Ask about trips, fuel, invoices..."
             onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} />
      <button onClick={ask} disabled={loading}>{loading ? "Thinking..." : "Ask"}</button>
    </div>
  );
}

function AssistantMessage({ message, loading, onToggleTable, onFeedback, onRunSql, onFix }) {
  const { result, error, feedback, table, tableOpen } = message;
  return (
    <div className="bubble assistant">
      {error && <p className="error">{error}</p>}
      {!result && !error && <p>Thinking...</p>}
      {result && (
        <>
          <ReactMarkdown>{result.answer}</ReactMarkdown>

          <button onClick={onToggleTable}>{tableOpen ? "Hide table" : "Show table"}</button>
          <button onClick={() => downloadCsv(result.id)}>Download CSV</button>

          {tableOpen && (
            <div className="details">
              {result.display === "chart" && (
                <Plot data={result.chart.data} layout={{ ...result.chart.layout, autosize: true }}
                      useResizeHandler style={{ width: "100%", height: 400 }} />
              )}
              <ResultTable table={table} />
              {result.sql && <pre>{result.sql}</pre>}
            </div>
          )}

          {!feedback && (
            <p>
              Were the results correct?{" "}
              <button onClick={() => onFeedback(true)}>Yes, train as Question-SQL pair</button>
              <button onClick={() => onFeedback(false)}>No</button>
            </p>
          )}
          {feedback === "trained" && <p>Thanks! Saved as an example.</p>}
          {feedback === "wrong" && (
            <CorrectionPanel sql={result.sql} loading={loading} onRunSql={onRunSql} onFix={onFix} />
          )}
        </>
      )}
    </div>
  );
}

// sql is null when sql_visible is off: then only "Fix it" (describe the problem) is offered
function CorrectionPanel({ sql, loading, onRunSql, onFix }) {
  const [editedSql, setEditedSql] = useState(sql ?? "");
  const [comment, setComment] = useState("");
  return (
    <div className="correction">
      <p>Tell us what's wrong:</p>
      <input placeholder="e.g. show one row per trip with its route"
             value={comment} onChange={(e) => setComment(e.target.value)} />
      <button disabled={loading || comment.trim().length < 3} onClick={() => onFix(comment)}>
        Fix it
      </button>

      {sql && (
        <>
          <p>Or edit the SQL yourself:</p>
          <textarea rows={8} value={editedSql} onChange={(e) => setEditedSql(e.target.value)} />
          <button disabled={loading} onClick={() => onRunSql(editedSql)}>Run SQL</button>
        </>
      )}
    </div>
  );
}

// table = the response of GET /api/results/{id}/table
function ResultTable({ table }) {
  return (
    <table>
      <thead><tr>{table.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>
        {table.rows.map((row, i) => (
          <tr key={i}>{table.columns.map((c) => <td key={c}>{row[c]}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}
```
