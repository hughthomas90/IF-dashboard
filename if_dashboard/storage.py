from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class CacheRecord:
    key: str
    payload: dict
    fetched_at: datetime


class CacheStore:
    def __init__(self, db_path: str, ttl_days: int = 7) -> None:
        self.db_path = db_path
        self.ttl_days = ttl_days
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, key: str) -> CacheRecord | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT cache_key, payload, fetched_at FROM api_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row[2])
        return CacheRecord(key=row[0], payload=json.loads(row[1]), fetched_at=fetched_at)

    def set(self, key: str, payload: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO api_cache(cache_key, payload, fetched_at)
                VALUES(?, ?, ?)
                ON CONFLICT(cache_key)
                DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at
                """,
                (key, json.dumps(payload), now),
            )
            conn.commit()

    def is_fresh(self, rec: CacheRecord) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
        fetched_at = rec.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        return fetched_at >= cutoff
