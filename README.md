# Ask the database (Vanna + Ollama + MySQL)

Ask questions in plain English and get SQL, a result table and a chart, using a
production MySQL database. Everything runs locally: the LLM through Ollama, the
training memory in ChromaDB. No schema or data leaves the machine.

Only the business tables listed in `config/tables.txt` are learned and queryable.
The technical tables are ignored.

## How it works

```
question ──► Vanna ──► finds related table DDL, business rules and example SQL in ChromaDB
                   ──► Ollama (qwen2.5:7b) writes a MySQL query
                   ──► safe_sql.py checks it, runs it read-only with a timeout and row cap
                   ──► table + Plotly chart in the web UI
```

| File | Purpose |
|---|---|
| `config/tables.txt` | Allowlist of business tables (one per line) |
| `config/hidden_columns.txt` | Confidential columns (password, Aadhaar, bank account, PAN, images): never trained on, never queryable |
| `training/documentation.md` | Business rules: metric definitions, status codes, filters |
| `training/examples.sql` | Verified question/SQL pairs |
| `train.py` | Loads the three files above into the vector store |
| `app.py` | Built-in web chat UI (Vanna's Flask app) |
| `api.py` | REST API for the React frontend: see [API.md](API.md) |
| `charts.py` | Builds the Plotly chart for API results from the column types |
| `safe_sql.py` | Read-only, single-SELECT, allowlist-only query execution |
| `settings.py` / `.env` | Configuration |

## Setup

1. **Configure**: copy `.env.example` to `.env` and fill in the MySQL details.

2. **List the business tables** in `config/tables.txt` and the confidential columns in
   `config/hidden_columns.txt`.

3. **Create a read-only MySQL user** that can only read the business tables and
   non-confidential columns. This is the real security boundary; the checks in
   `safe_sql.py` are a second layer. Generate the SQL, set a password in it, run it as
   an admin, then put the new user in `.env`:

   ```
   .venv\Scripts\python train.py --grants vanna_readonly > readonly_user.sql
   ```

4. **Install** (already done in `.venv`):

   ```
   .venv\Scripts\python -m pip install -r requirements.txt
   ```

5. **Check, then train**:

   ```
   .venv\Scripts\python train.py --dry-run   # shows the DDL it will learn
   .venv\Scripts\python train.py
   ```

6. **Run the web app**, then open http://127.0.0.1:8084:

   ```
   .venv\Scripts\python app.py
   ```

7. **Or run the REST API** for the React frontend, then open http://127.0.0.1:8000/docs:

   ```
   .venv\Scripts\python api.py
   ```

   Answers marked "No" are logged to `feedback/wrong_answers.jsonl`. Review them
   regularly and fix them with documentation or examples.

Re-run `train.py` whenever you change tables, documentation or examples. It rebuilds
schema and documentation from scratch. Question/SQL pairs that users mark as correct in
the UI are kept, unless you pass `--reset-examples`.

## Getting good accuracy

The schema alone is rarely enough on a real database. In order of impact:

1. **Examples** (`training/examples.sql`): 20-50 verified queries for the questions
   people really ask, especially ones with tricky joins or metric definitions.
2. **Documentation** (`training/documentation.md`): what statuses and codes mean, how
   revenue/margin/etc. are calculated, default filters (soft deletes, test data), time
   zones, currency units.
3. **Column comments** in MySQL. `train.py` picks up table and column `COMMENT`s
   automatically.
4. **A bigger model.** `qwen2.5:7b` works but makes mistakes on complex queries.
   If the hardware allows, try `ollama pull qwen2.5-coder:14b` and set `OLLAMA_MODEL`.

In the UI, when an answer is right, click to save it. It becomes a new example.

## Before exposing it to other people

- The UI has **no login**. Keep `APP_HOST=127.0.0.1`, or put it behind a reverse proxy
  with authentication / VPN before setting `0.0.0.0`.
- `app.py` uses Flask's built-in server, which is fine for a small team. For more users,
  run it behind a production WSGI server.
- Set `SHOW_TRAINING_DATA=false` if users shouldn't see or edit the training data.
