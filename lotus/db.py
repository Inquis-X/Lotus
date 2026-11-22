import sqlite3
from contextlib import contextmanager
from pathlib import Path
from lotus.settings import DB_PATH


@contextmanager
def connection(path: Path | None = None):
    target = Path(path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(path=None):
    with connection(path) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS records (
          model TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(model, id)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          actor TEXT NOT NULL, action TEXT NOT NULL, object_type TEXT NOT NULL,
          object_id TEXT NOT NULL, details TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_documents (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          source_kind TEXT NOT NULL,
          origin TEXT NOT NULL,
          uri TEXT,
          media_type TEXT,
          sha256 TEXT,
          registered_at TEXT NOT NULL,
          synthetic INTEGER NOT NULL,
          details TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_links (
          context_type TEXT NOT NULL,
          context_id TEXT NOT NULL,
          source_kind TEXT NOT NULL,
          source_id TEXT NOT NULL,
          locator TEXT NOT NULL DEFAULT '',
          document_id TEXT NOT NULL REFERENCES source_documents(id),
          PRIMARY KEY(context_type, context_id, source_kind, source_id, locator)
        );
        ''')
