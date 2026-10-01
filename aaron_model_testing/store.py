from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .util import canonical, write_json

TABLES = {"models", "profiles", "runs", "jobs"}


class Store:
    """Small JSON record index. Durable JSON/JSONL artifacts remain the source of truth."""

    def __init__(self, home: Path):
        self.home = home
        home.mkdir(parents=True, exist_ok=True)
        self.path = home / "index.sqlite3"
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            for table in TABLES:
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, table: str, record: dict):
        if table not in TABLES:
            raise ValueError(table)
        # File first, index second: a failed DB write can be recovered with reindex.
        write_json(self.home / table / (record["id"] + ".json"), record)
        self.index(table, record)

    def index(self, table, record):
        if table not in TABLES:
            raise ValueError(table)
        with self.connection() as db:
            db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (record["id"], canonical(record)))

    def get(self, table: str, record_id: str):
        if table not in TABLES:
            raise ValueError(table)
        with self.connection() as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (record_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, table: str) -> list[dict]:
        if table not in TABLES:
            raise ValueError(table)
        with self.connection() as db:
            rows = db.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    def reindex(self):
        counts = {}
        for table in TABLES:
            count = 0
            for path in sorted((self.home / table).glob("*.json")):
                self.index(table, json.loads(path.read_text(encoding="utf-8")))
                count += 1
            counts[table] = count
        return counts
