"""
Резервное копирование проекта.

Что сохраняется в папку backups/<дата>/:
- rent.dump — полная копия базы PostgreSQL (программа pg_dump);
- файлы модели и подготовленные данные.
Файлы бронзового слоя копируются в backups/bronze/ только один раз, потому что не меняются.
Хранятся 5 последних копий. Если в .env задан BACKUP_COPY_DIR (например, папка облачного
диска или флешка), всё дублируется туда: копия на том же диске не спасёт при его поломке.

Запуск:
    venv\\Scripts\\python.exe src\\backup.py            создать копию
    venv\\Scripts\\python.exe src\\backup.py --check    создать копию и проверить восстановление
"""

import argparse
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from db import connect, read_env

PROJECT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_DIR / "backups"
KEEP = 5
CHECK_DB = "rent_restore_check"
TABLES = ["load_runs", "offers", "price_history", "offers_model", "model_runs", "quality_checks", "pipeline_runs"]


def pg_tool(name):
    """Путь к программе PostgreSQL (pg_dump, pg_restore)."""
    found = shutil.which(name)
    if found:
        return found
    default = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\17\bin")) / f"{name}.exe"
    if not default.exists():
        raise FileNotFoundError(f"Не найдена программа {name}. Укажите папку в PG_BIN в файле .env")
    return str(default)


def run_tool(*command):
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{Path(command[0]).name}: {result.stderr.strip()[:500]}")


def copy_bronze(target):
    """Докладывает в target только новые файлы бронзового слоя."""
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in (PROJECT_DIR / "data" / "bronze").glob("offers_*"):
        if not (target / path.name).exists():
            shutil.copy2(path, target / path.name)
            copied += 1
    return copied


def rotate(folder):
    """Оставляет KEEP последних датированных копий."""
    dated = sorted(p for p in folder.iterdir() if p.is_dir() and p.name[:4].isdigit())
    for old in dated[:-KEEP]:
        shutil.rmtree(old)


def create_backup():
    """Создаёт резервную копию и возвращает путь к её папке."""
    read_env()
    target = BACKUP_DIR / datetime.now().strftime("%Y-%m-%d_%H%M")
    target.mkdir(parents=True, exist_ok=True)
    run_tool(pg_tool("pg_dump"), "--format=custom", f"--file={target / 'rent.dump'}", os.environ["PGDATABASE"])
    data = PROJECT_DIR / "data"
    for path in [*(PROJECT_DIR / "models").glob("*.*"), *(data / "silver").glob("*"), *(data / "gold").glob("*"),
                 *(data / "reference").glob("*")]:
        shutil.copy2(path, target / path.name)
    new_raw = copy_bronze(BACKUP_DIR / "bronze")
    rotate(BACKUP_DIR)

    extra = os.environ.get("BACKUP_COPY_DIR")
    if extra:
        extra = Path(extra)
        shutil.copytree(target, extra / target.name, dirs_exist_ok=True)
        copy_bronze(extra / "bronze")
        rotate(extra)
    size = sum(p.stat().st_size for p in target.iterdir()) / 1e6
    print(f"Резервная копия: {target} ({size:.1f} МБ), новых файлов бронзового слоя {new_raw}, "
          f"вторая копия: {'есть' if extra else 'не настроена'}")
    return target


def counts(dbname):
    with connect(dbname) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def check_restore(target):
    """Восстанавливает копию во временную базу и сравнивает число строк с рабочей базой."""
    with connect("postgres") as conn:
        conn.autocommit = True
        conn.execute(f"DROP DATABASE IF EXISTS {CHECK_DB}")
        conn.execute(f"CREATE DATABASE {CHECK_DB}")
    try:
        run_tool(pg_tool("pg_restore"), "--no-owner", f"--dbname={CHECK_DB}", str(target / "rent.dump"))
        original, restored = counts(os.environ["PGDATABASE"]), counts(CHECK_DB)
    finally:
        with connect("postgres") as conn:
            conn.autocommit = True
            conn.execute(f"DROP DATABASE IF EXISTS {CHECK_DB}")
    for table in TABLES:
        print(f"{table:15} в базе {original[table]:6}, в копии {restored[table]:6}")
    print("Восстановление проверено: совпадает" if original == restored else "ОШИБКА: копия отличается")
    return original == restored


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="проверить восстановление копии")
    args = parser.parse_args()
    path = create_backup()
    if args.check and not check_restore(path):
        raise SystemExit(1)
