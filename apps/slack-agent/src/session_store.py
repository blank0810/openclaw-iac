import sqlite3
from contextlib import contextmanager
from pathlib import Path


class SessionStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS threads (
                    thread_key TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
                )"""
            )

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get(self, thread_key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT session_id FROM threads WHERE thread_key = ?", (thread_key,)
            ).fetchone()
            return row[0] if row else None

    def put(self, thread_key: str, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO threads (thread_key, session_id) VALUES (?, ?)",
                (thread_key, session_id),
            )
