"""
Проверка обновления на свежих данных без изменения рабочей базы.

Последняя резервная копия восстанавливается во временную базу, туда дважды загружается указанный
файл бронзового слоя, затем временная база удаляется.

Запуск:
    venv\\Scripts\\python.exe src\\check_fresh_load.py data\\bronze\\rejected\\offers_<дата>.jsonl
"""

import os
import subprocess
import sys
from pathlib import Path

from backup import BACKUP_DIR, pg_tool, run_tool
from db import connect, read_env

TEST_DB = "rent_fresh_check"
LAKE = Path(__file__).resolve().parent / "lake.py"


def main(path):
    read_env()
    working = os.environ["PGDATABASE"]
    dump = sorted(p for p in BACKUP_DIR.iterdir() if p.name[:4].isdigit())[-1] / "rent.dump"
    with connect("postgres") as conn:
        conn.autocommit = True
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    try:
        run_tool(pg_tool("pg_restore"), "--no-owner", f"--dbname={TEST_DB}", str(dump))
        code = ("import sys; sys.path.insert(0, r'%s'); from lake import DataLakeManager; "
                "DataLakeManager().load_silver(r'%s')" % (LAKE.parent, path))
        env = dict(os.environ, PGDATABASE=TEST_DB, PYTHONIOENCODING="utf-8")
        for attempt in ("Первая загрузка", "Повторная загрузка"):
            out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8")
            print(attempt + ":", out.stdout.strip(), out.stderr.strip()[-300:])
        with connect(TEST_DB) as conn:
            for row in conn.execute("SELECT run_id, offers_count, new_offers, price_changes FROM load_runs ORDER BY run_id"):
                print("сбор", row[0], "объявлений", row[1], "новых", row[2], "изменений цены", row[3])
            print("записей в истории цен:", conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0])
    finally:
        with connect("postgres") as conn:
            conn.autocommit = True
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    with connect(working) as conn:
        print("рабочая база: объявлений", conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0],
              "сборов", conn.execute("SELECT COUNT(*) FROM load_runs").fetchone()[0])


if __name__ == "__main__":
    main(sys.argv[1])
