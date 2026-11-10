import sqlite3
from decimal import Decimal
from pathlib import Path

from .config import DB_PATH

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Money is rounded (money.py) before it is written, so storing it as REAL is
# exact; this lets a Decimal be passed straight to a query.
sqlite3.register_adapter(Decimal, float)


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # LangGraph may run a node on a worker thread; access stays sequential.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the UI keep reading while a background run writes.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
