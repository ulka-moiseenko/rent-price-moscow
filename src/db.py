"""
Подключение к базе PostgreSQL.

Параметры подключения (адрес, порт, имя базы, пользователь, пароль) берутся
из файла .env в папке проекта. Пароль не хранится в коде и не попадает на GitHub.
"""

import os
from pathlib import Path

import psycopg

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_DIR / ".env"


def read_env(path=ENV_PATH):
    """Читает строки вида КЛЮЧ=значение из .env в переменные окружения."""
    if not path.exists():
        raise FileNotFoundError(f"Нет файла {path} с параметрами подключения к базе")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def connect(dbname=None):
    """Открывает соединение с PostgreSQL (psycopg сам берёт PGHOST, PGPASSWORD и т.д.).

    Сообщения сервера переключаются на английский: русские приходят в кодировке
    Windows-1251 и в Python отображаются нечитаемыми символами.
    """
    read_env()
    kwargs = {"dbname": dbname} if dbname else {}
    return psycopg.connect(options="-c lc_messages=C", **kwargs)


def create_database_if_missing():
    """Создаёт базу из PGDATABASE, если её ещё нет на сервере."""
    read_env()
    name = os.environ["PGDATABASE"]
    with connect("postgres") as conn:
        conn.autocommit = True  # CREATE DATABASE нельзя выполнять внутри транзакции
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')
            print(f"Создана база данных {name}")


if __name__ == "__main__":
    create_database_if_missing()
    with connect() as conn:
        version = conn.execute("SELECT version()").fetchone()[0]
        db = conn.execute("SELECT current_database(), current_user").fetchone()
    print("Подключение успешно:", version.split(",")[0])
    print("База:", db[0], "| пользователь:", db[1])
