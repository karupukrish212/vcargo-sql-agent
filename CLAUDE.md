# VCargo SQL Agent: session handover (updated 2026-11-03)

Fleet data assistant: staff ask plain-English questions about the fleet/transport MySQL database and get
SQL, rows, a chart and CSV. Vanna 0.7.9 + ChromaDB 0.6.3 (`vector_store/`) + Groq. FastAPI `api.py`
(port 8001, used by the React frontend, see API.md) and the Flask Vanna UI `app.py` (port 8084).

Run: `.venv\Scripts\python api.py` (Python 3.12.0 venv). Train: `.venv\Scripts\python train.py` (`--dry-run`, `--reset-examples`).

## Working rules
- Explain to the user in Tamil and keep technical terms, code, SQL and paths in English.
- Never read, print or edit secret values in `.env`. The user edits `.env` themselves.
- ChromaDB is not multi-process safe. Never write to `vector_store/` from another process while the API runs.
  Run `train.py` with the API stopped, or restart the API afterwards.
- Commit only when the user asks. Work on branch `dev`. `main` is the PR target. Last commit is `02f3a55`
  and contains all work up to 2026-11-02.

## 1. Phases
| # | Phase | Status |
|---|---|---|
| 1 | Analyse the project | done |
| 2 | Groq only: Ollama code commented out (not deleted) in settings.py, vanna_client.py, requirements.txt, .env.example | done, committed |
| 3 | New `.venv` on this machine (Python 3.12.0) | done |
| 4 | Training flow: `training/examples.sql` auto-synced, "Yes" saves to the store and the file | done, committed |
| 5 | Accuracy: city with two names (Bangalore/Bengaluru) | **in progress**: doc rule and example done; "from bangalore" still wrong |
| 6 | Evaluation (eval set, accuracy report) | not started |
| 7 | Deploy to the office Windows Server without source code | **current phase**: plan given, nothing built yet |
| 8 | Docs cleanup (README/API.md) | not started |
| 9 | Chat-style written answer: `POST /api/results/{id}/answer` (`answers.py`), React chat example in API.md | done 2026-11-03, not committed |
| 10 | Table only on "Show table": `"rows": false` on ask/run-sql/fix + `GET /api/results/{id}/table` | done 2026-11-03, not committed |
| 11 | `"answer": true` (answer in the /ask response, one call) and `"sql_visible"` on ask/run-sql/fix | done 2026-11-03, not committed; user may ask for changes after trying it |

## 2. Decisions and why
- **Model:** Groq `openai/gpt-oss-120b` through the OpenAI-compatible API, `reasoning_effort=low`, `LLM_PROMPT_TOKENS=12288`.
  The user wants a single provider. The Ollama code is commented out, not deleted, so it can be turned back on.
- **Scope tables:** `config/tables.txt` lists 18 business tables. Every other table is never trained on or queried.
- **Sensitive columns:** `config/hidden_columns.txt` lists users.password, tdriver.aadharnumber,
  companybankdetails.accountnumber, customer.pannumber and companyprofile.panno, plus the image columns
  companyprofile.companylogo and customer.image.
  These columns are removed from the trained schema, any query that mentions them is rejected, and `SELECT *` is rejected on their tables.
- **Guard rules (`safe_sql.py`):** single SELECT only, allowlisted tables only, no hidden columns, no
  INTO OUTFILE / FOR UPDATE / SLEEP etc., read-only transaction, `MAX_EXECUTION_TIME` (`QUERY_TIMEOUT_SECONDS`=30),
  row cap `MAX_RESULT_ROWS`=5000. A read-only MySQL user is the first line of defence (`train.py --grants USER`).
- **Date handling** (`training/documentation.md`, "Dates"): use the real DATE columns.
  createdon and modifiedon are TEXT ('DD-MM-YYYY hh:mm:ss AM'), so convert them with STR_TO_DATE and only when no business date exists.
  Every date range needs both a start and an end.
- **Places:** trip.source and trip.destination hold full addresses, so match them with `LIKE '%name%'`.
  A city with two names is matched on both names, with the OR inside brackets. The alias list is in documentation.md.
- **Training:** `training/examples.sql` is the source of truth. The API trains new examples before the next question (it checks the file's mtime).
  "Yes" (`POST /api/results/{id}/feedback {"correct": true}`) saves to the store and to examples.sql with the label
  `-- Added from the app on <date>`, replacing any earlier SQL for the same question. DELETE removes the example from both.
  Saving happens on "Yes", not automatically on run-sql, because SQL that runs is not necessarily correct.
  Only the user's confirmation should train. The Flask page's "Yes" trains only the vector store.
- `ALLOW_LLM_TO_SEE_DATA` defaults to false. Setting it to true sends result rows to Groq.
  It also lets Vanna run lookup queries while writing SQL.
- **Written answer** (`answers.py`, `POST /api/results/{id}/answer`): a separate endpoint, so a Groq failure never hides the table.
  - With `ALLOW_LLM_TO_SEE_DATA=true`, Groq writes the Markdown answer from the first `ANSWER_MAX_ROWS`=50 rows and streams it.
  - With `false`, or when Groq fails, rate-limits or writes nothing, `template_answer()` builds it from the result and nothing is sent.
  - The `X-Answer-Source` header (`llm` / `template`) says which one wrote it.
  - Code formats the values (₹ with Indian grouping, dates such as `02 Nov 2026`) and Groq copies them and must not calculate.
  - The answer is not trained; only the SQL is trained.
  - The user first wanted no result data sent to the LLM, then chose this design and set `ALLOW_LLM_TO_SEE_DATA=true` in `.env` on 2026-11-03.
  - The LLM path was first tested with made-up rows. After the flag was set to true, one real end-to-end `/api/ask` test was run.
- **Response options** (`ResultOptions` in api.py, shared by ask/run-sql/fix):
  - `chart` (default true).
  - `rows` (default true; false gives `rows: null`, and the table comes from `GET /table` on click).
  - `answer` (default false; true adds `answer` + `answer_source` via `whole_answer()`, about 1-2 s more, and falls back to the template).
  - `sql_visible` (**default false, the user's choice**): SQL is null in responses and in error details unless true.
    This changed earlier behaviour: SQL used to be always returned.
  - The user's chat body is `{"question", "chart": true, "rows": false, "answer": true}`.

## 3. Open questions / waiting for approval
1. **Option A (city aliases):** when a question names a two-name city, the API adds a hint such as
   "Bangalore is also written Bengaluru in the data: match both names". The original question is still the one saved.
   Not approved yet. Alternatives: B = more examples, C = normalise the data at the source.
2. **`RETRIEVAL_RESULTS` appears twice in `.env`** (10 and 6, and the last one, 6, wins). The user must choose between 6 and 10 and fix `.env`.
3. **Deployment inputs:** does the office server have internet access (Groq; first-run ChromaDB embedding model, about 80 MB)?
   What URL will the React app use (for `CORS_ORIGINS`)?
4. **Extra Windows service to remove: unconfirmed.** This session has no record of which one it is.
   On this dev machine, no VCargo, WinSW, uvicorn or Python service exists (checked 2026-11-03).
   On the office server, list the candidates and check each PathName before deleting anything. Ask the user to confirm the name:
   `Get-CimInstance Win32_Service | ? { $_.PathName -match 'vcargo|winsw|uvicorn|python' } | select Name,DisplayName,State,PathName`
5. Approval to do the deployment code changes and the PyInstaller build (step 2 below).

## 4. Eval results
- **No eval has been run.** No eval set, eval script or report file exists, so there are no accuracy numbers.
- Manual checks only (2026-11-02):
  - "customers from dindigul to bangalore": correct after the fix.
  - "how many trips from bangalore?": **wrong**. Groq wrote only `LIKE '%bangalore%'` and returned 0, but the true answer is 1 (the one trip is written 'Bengaluru').
  - Weak category: place names and city aliases.
- What to try next:
  - Build an eval set (questions + expected SQL/result), including alias, date-range and cancel=0 cases.
  - Run it against the live API and save a dated report.
  - Then measure Option A and the effect of `RETRIEVAL_RESULTS` (6 vs 10).

## 5. Deployment
**Status: not built and not installed.** These are planned unless marked as fact.
- **Fact:** WinSW `VCargoSQLAgentService.exe` + `.xml`, service id `VCargoSQLAgent`, display name "VCargo SQL Agent API", automatic start, restart on failure.
  The current XML runs `C:\vcargo-sql-agent\.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8001`, with logs in `C:\vcargo-sql-agent\logs`.
  `logs/VCargoSQLAgentService.wrapper.log` shows it was started on 2026-10-27 on some machine that had `C:\vcargo-sql-agent`.
- **Planned build:** PyInstaller one-folder build on the dev machine, giving `VCargoSQLAgent.exe` + `_internal\`. No `.py` files and no Python are needed on the server.
  Two code changes are needed first:
  1. `settings.py`: when frozen, resolve ROOT from the exe's folder.
  2. A launcher: `VCargoSQLAgent.exe` runs the API, and `VCargoSQLAgent.exe train` runs training.

  ChromaDB needs extra PyInstaller options (untested).
  This hides the source but is not real protection, because code can be extracted from the exe. Real protection is controlling who can log in to the server.
- **Planned install:** `C:\vcargo-sql-agent\` on the office server, containing:
  - the exe and `_internal\`
  - the WinSW exe and XML (`<executable>` = the app exe, no `<arguments>`)
  - `.env`, `config\`, `training\`, `vector_store\`, `feedback\`

  Server `.env` needs `MYSQL_HOST`, `API_HOST=0.0.0.0`, a strong `API_KEY` and `CORS_ORIGINS`.
  Allow inbound TCP 8001 in the firewall. Test with `/docs` and `/api/health`.
- **Upgrade:** rebuild, stop the service, back up the current exe + `_internal\` to a dated folder, replace only those two, start the service.
  Never overwrite `.env`, `config\`, `training\`, `vector_store\` or `feedback\`, because they hold server-side examples and feedback.
- **Rollback:** stop the service, restore the backed-up exe + `_internal\`, start the service.
- **Known issues:**
  - The current XML points to a `.venv` path that does not exist on this machine.
  - The 18 MB WinSW exe and the wrapper log are committed to git.
  - API is single-process, and its result cache (60 min) is in memory.
  - `.env` lacks `API_KEY` and `CORS_ORIGINS`, so there is no key and it allows localhost:3000/5173 only.
  - The vector store holds an old "natham to madurai ?" Yes-example that is not in examples.sql.
  - README and API.md still mention Ollama and a local model, API.md lacks 429/503, and the /api/health example is outdated.

## 6. Next 3 steps
1. Get the user's answers to open questions 1-3, plus the name of the service to remove (question 4).
2. With approval, make the `settings.py` frozen-path change and the launcher, install PyInstaller in `.venv`, and build.
   Test the exe on a copy (API + `train`), and update `VCargoSQLAgentService.xml` to the exe.
3. Deploy to the office server (copy, configure `.env`, check service PathNames, install/start the service, open the firewall)
   and verify `/api/health`. Then start phase 6 (eval set + first report).
