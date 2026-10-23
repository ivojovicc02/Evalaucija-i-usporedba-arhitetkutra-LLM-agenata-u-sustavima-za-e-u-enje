"""
Bulk-insert svih zadataka (tasks/*.json) u tabelu `tasks`.

Pokretanje (iz korijena projekta, s podignutom bazom):
    pip install psycopg2-binary
    python db/load_tasks.py

Konekcija se uzima iz env varijabli (default vrijednosti odgovaraju
docker-compose.yml postavkama).
"""

import json
import os
from pathlib import Path

import psycopg2

DB_HOST = os.environ.get("ELT_DB_HOST", "localhost")
DB_PORT = os.environ.get("ELT_DB_PORT", "5432")
DB_NAME = os.environ.get("ELT_DB_NAME", "elt_agents")
DB_USER = os.environ.get("ELT_DB_USER", "elt_admin")
DB_PASSWORD = os.environ.get("ELT_DB_PASSWORD", "change_me_locally")

TASKS_DIR = Path(__file__).parent.parent / "tasks"


def load_task_files() -> list[dict]:
    tasks = []
    for path in sorted(TASKS_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["_source_file"] = path.name
            tasks.append(data)
    return tasks


def main() -> None:
    tasks = load_task_files()
    print(f"Pronađeno {len(tasks)} task fajlova u {TASKS_DIR}")

    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute("SELECT code, id FROM concepts;")
        concept_map = dict(cur.fetchall())

        inserted, skipped = 0, 0
        for task in tasks:
            concept_code = task["concept_code"]
            if concept_code not in concept_map:
                print(f"  [PRESKOČENO] {task['_source_file']}: nepoznat concept_code '{concept_code}'")
                skipped += 1
                continue

            cur.execute(
                "SELECT id FROM tasks WHERE title = %s AND concept_id = %s;",
                (task["title"], concept_map[concept_code]),
            )
            if cur.fetchone():
                print(f"  [POSTOJI] {task['_source_file']}: '{task['title']}' već u bazi, preskačem")
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO tasks (concept_id, difficulty, title, prompt, entry_point, starter_code, test_cases, common_errors)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    concept_map[concept_code],
                    task["difficulty"],
                    task["title"],
                    task["prompt"],
                    task["entry_point"],
                    task.get("starter_code"),
                    json.dumps(task["test_cases"]),
                    json.dumps(task.get("common_errors", [])),
                ),
            )
            inserted += 1
            print(f"  [UBAČENO] {task['_source_file']}: '{task['title']}'")

        conn.commit()
        print(f"\nGotovo. Ubačeno: {inserted}, preskočeno: {skipped}.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()