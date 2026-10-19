"""SQLite connection helper + SAP-style RETURN table builder."""
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "data/erp.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "schema.sql")
MIGRATIONS = [
    os.path.join(os.path.dirname(__file__), "..", "data", f"migration_{version:03d}.sql")
    for version in (1, 2)
]


def db_exists(path: str = DB_PATH) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def init_schema(path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f"BEGIN;\n{f.read()}\nPRAGMA user_version = {len(MIGRATIONS)};\nCOMMIT;")
    finally:
        conn.close()


def migrate_schema(path: str = DB_PATH) -> None:
    """Upgrade an existing database once; leave its historical postings untouched."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, path_file in enumerate(MIGRATIONS, 1):
            if current >= version:
                continue
            # executescript commits implicitly; wrap each version in its own transaction.
            with open(path_file, "r", encoding="utf-8") as f:
                conn.executescript(f"BEGIN;\n{f.read()}\nPRAGMA user_version = {version};\nCOMMIT;")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_conn(path: str = None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows_to_dicts(rows) -> list:
    return [dict(r) for r in rows]


def bapi_result(data=None, messages=None) -> dict:
    """Mimic a real BAPI's RETURN table + payload shape."""
    ret = messages or [{"type": "S", "message": "Operation completed successfully"}]
    result = {"RETURN": ret}
    if data is not None:
        result["DATA"] = data
    return result


def bapi_error(message: str) -> dict:
    return {"RETURN": [{"type": "E", "message": message}]}
