"""Train Vanna on the business tables only.

    python train.py                  rebuild schema + documentation, add examples
    python train.py --reset-examples also wipe question/SQL pairs (incl. ones saved from the web UI)
    python train.py --dry-run        print what would be trained, change nothing
    python train.py --grants USER    print SQL that creates a read-only MySQL user for .env

Schema and documentation are rebuilt from scratch on every run, so the store always
matches config/tables.txt, config/hidden_columns.txt and training/documentation.md.
Question/SQL pairs are kept by default because users add good ones from the web UI.
"""
import argparse
import re
import sys

import settings
from safe_sql import explain, fetch_rows


def table_ddl(name: str, hidden: set[str]) -> str:
    ddl = fetch_rows(f"SHOW CREATE TABLE `{name}`")[0][1]
    # Drop storage options (ENGINE, CHARSET, AUTO_INCREMENT counter...) but keep the table comment
    match = re.search(r"\)\s*ENGINE=.*$", ddl, re.DOTALL)
    if match:
        comment = re.search(r"COMMENT='((?:[^'\\]|\\.|'')*)'", match.group(0))
        ddl = ddl[: match.start()] + ")" + (f" COMMENT='{comment.group(1)}'" if comment else "")

    lines = []
    for line in ddl.splitlines():
        stripped = line.strip()
        # Hidden columns, and any key/constraint that mentions one
        if any(f"`{col}`" in stripped.lower() for col in hidden):
            continue
        # Plain indexes only cost prompt space; keep primary, unique and foreign keys
        if stripped.startswith("KEY ") or stripped.startswith("FULLTEXT KEY "):
            continue
        line = re.sub(r"CONSTRAINT `\w+` FOREIGN KEY", "FOREIGN KEY", line)
        line = re.sub(r"UNIQUE KEY `\w+`", "UNIQUE KEY", line)
        lines.append(line)
    return re.sub(r",(\s*\n\))", r"\1", "\n".join(lines)) + ";"


def grants_sql(user: str, tables: list[str], hidden: dict[str, set[str]]) -> str:
    db = settings.MYSQL_DATABASE
    account = f"'{user}'@'localhost'"
    out = [
        f"-- Run as an admin. Then put {user} and the password in .env",
        f"CREATE USER IF NOT EXISTS {account} IDENTIFIED BY '<choose-a-strong-password>';",
    ]
    for t in tables:
        if t.lower() in hidden:
            cols = [c for (c,) in fetch_rows(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (db, t))
                if c.lower() not in hidden[t.lower()]]
            col_list = ", ".join(f"`{c}`" for c in cols)
            out.append(f"GRANT SELECT ({col_list}) ON `{db}`.`{t}` TO {account};")
        else:
            out.append(f"GRANT SELECT ON `{db}`.`{t}` TO {account};")
    return "\n".join(out)


def load_documentation() -> list[str]:
    """Chunks of training/documentation.md separated by a line containing only ---."""
    if not settings.DOCUMENTATION_FILE.exists():
        return []
    text = re.sub(r"<!--.*?-->", "", settings.DOCUMENTATION_FILE.read_text(encoding="utf-8"), flags=re.DOTALL)
    chunks = re.split(r"^\s*---\s*$", text, flags=re.MULTILINE)
    return [c.strip() for c in chunks if re.sub(r"^#.*$", "", c, flags=re.MULTILINE).strip()]


_QUESTION_LINE = re.compile(r"^\s*--\s*Q:\s*(.+)$")


def load_examples() -> list[tuple[str, str]]:
    """Pairs from training/examples.sql: a '-- Q: question' line followed by its SQL.
    Other comment lines (like '-- Added from the app on ...') are not part of the SQL."""
    if not settings.EXAMPLES_FILE.exists():
        return []
    examples, question, sql_lines = [], None, []
    for line in settings.EXAMPLES_FILE.read_text(encoding="utf-8").splitlines():
        m = _QUESTION_LINE.match(line)
        if m:
            if question and "".join(sql_lines).strip():
                examples.append((question, "\n".join(sql_lines).strip()))
            question, sql_lines = m.group(1).strip(), []
        elif question and not line.lstrip().startswith("--"):
            sql_lines.append(line)
    if question and "".join(sql_lines).strip():
        examples.append((question, "\n".join(sql_lines).strip()))
    return examples


def question_key(question: str) -> str:
    """For comparing questions: case and extra spaces don't make a different question."""
    return " ".join(question.split()).lower()


def write_example(question: str, sql: str, note: str | None = None) -> None:
    """Put a pair in training/examples.sql, replacing the example with the same question if there is one."""
    sql = "\n".join(sql.strip().rstrip(";").rstrip().splitlines()) + ";"
    block = [f"-- Q: {' '.join(question.split())}"] + ([f"-- {note}"] if note else []) + [sql]
    _rewrite_examples(question, block)


def remove_example(question: str) -> bool:
    """Remove the examples with this question from training/examples.sql."""
    return _rewrite_examples(question, None)


def _rewrite_examples(question: str, block: list[str] | None) -> bool:
    """Replace the examples with this question by block (append it if there are none), or
    remove them when block is None. Other examples, comments and line endings are kept."""
    path = settings.EXAMPLES_FILE
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    starts = [i for i, line in enumerate(lines) if _QUESTION_LINE.match(line)]
    matches = [i for i in starts if question_key(_QUESTION_LINE.match(lines[i]).group(1)) == question_key(question)]
    if not matches and block is None:
        return False

    out, pos = [], 0
    for n, start in enumerate(matches):
        end = next((i for i in starts if i > start), len(lines))
        out += lines[pos:start]
        if n == 0 and block:
            out += block
            # Keep the blank lines before the next example
            while end > start and not lines[end - 1].strip():
                end -= 1
        pos = end
    out += lines[pos:]
    if not matches:
        while out and not out[-1].strip():
            out.pop()
        out += ([""] if out else []) + block + [""]

    with path.open("w", encoding="utf-8", newline=newline) as f:
        f.write("\n".join(out))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset-examples", action="store_true", help="also remove all question/SQL pairs")
    parser.add_argument("--dry-run", action="store_true", help="print what would be trained, change nothing")
    parser.add_argument("--grants", metavar="USER", help="print SQL to create a read-only MySQL user, then exit")
    args = parser.parse_args()

    wanted = settings.load_business_tables()
    hidden = settings.load_hidden_columns()
    in_db = {name.lower(): name for name, _ in fetch_rows("SHOW FULL TABLES")}
    missing = [t for t in wanted if t.lower() not in in_db]
    if missing:
        sys.exit(f"These tables in {settings.TABLES_FILE.name} don't exist in {settings.MYSQL_DATABASE}: {', '.join(missing)}")
    tables = [in_db[t.lower()] for t in wanted]

    if args.grants:
        print(grants_sql(args.grants, tables, hidden))
        return

    print(f"{len(tables)} business tables selected, {len(in_db) - len(tables)} technical tables ignored")
    ddls = [table_ddl(t, hidden.get(t.lower(), set())) for t in tables]
    docs = load_documentation()
    examples = []
    for question, sql in load_examples():
        try:
            explain(sql, set(tables), hidden)
            examples.append((question, sql))
        except Exception as e:
            print(f"  SKIPPED example '{question}': {e}")

    if args.dry_run:
        for d in ddls:
            print("\n" + d)
        print(f"\nWould train: {len(ddls)} DDL, {len(docs)} documentation chunks, {len(examples)} examples")
        return

    from vanna_client import build_vanna

    vn = build_vanna()
    vn.remove_collection("ddl")
    vn.remove_collection("documentation")
    if args.reset_examples:
        vn.remove_collection("sql")

    for d in ddls:
        vn.add_ddl(d)
    for doc in docs:
        vn.add_documentation(doc)
    existing = set(vn.get_training_data().query("training_data_type == 'sql'")["question"])
    added = 0
    for question, sql in examples:
        if question not in existing:
            vn.add_question_sql(question=question, sql=sql)
            added += 1

    counts = vn.get_training_data()["training_data_type"].value_counts().to_dict()
    print(f"Trained: {len(ddls)} DDL, {len(docs)} documentation chunks, {added} new examples")
    print(f"Vector store now holds: {counts}")


if __name__ == "__main__":
    main()
