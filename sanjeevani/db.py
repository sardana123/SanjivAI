"""Thread-safe SQLite wrapper and schema."""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    caregiver_name TEXT NOT NULL DEFAULT '',
    caregiver_contact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    dose TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    times TEXT NOT NULL,
    min_gap_hours REAL NOT NULL DEFAULT 3,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dose_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
    scheduled_for TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending | taken | missed | skipped
    responded_at TEXT,
    note TEXT NOT NULL DEFAULT '',
    alerted INTEGER NOT NULL DEFAULT 0,          -- escalation level already sent (0,1,2)
    snooze_until TEXT,
    UNIQUE (medication_id, scheduled_for)
);
CREATE INDEX IF NOT EXISTS idx_dose_patient_time ON dose_events(patient_id, scheduled_for);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    medication_id INTEGER,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a write statement; returns lastrowid."""
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur.lastrowid or 0

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
