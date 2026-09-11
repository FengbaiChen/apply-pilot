import sqlite3
from pathlib import Path

class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:": Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_question TEXT NOT NULL, normalized_question TEXT NOT NULL,
                answer TEXT NOT NULL, answer_type TEXT NOT NULL DEFAULT 'text',
                company TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL, approved_by_user INTEGER NOT NULL DEFAULT 0,
                times_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS answer_lookup ON answers(normalized_question, approved_by_user);
        """)
        self.connection.commit()

    def close(self):
        self.connection.close()
