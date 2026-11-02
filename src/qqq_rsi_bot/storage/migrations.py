"""SQLite schema migrations."""

from __future__ import annotations

import sqlite3

_MIGRATIONS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        signal_id TEXT,
        payload TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        signal_id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL,
        strategy_hash TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        idempotency_key TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        limit_price REAL,
        status TEXT NOT NULL,
        broker_order_id TEXT,
        order_ref TEXT NOT NULL,
        filled_qty INTEGER NOT NULL DEFAULT 0,
        avg_price REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_ref TEXT NOT NULL,
        signal_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        ts TEXT NOT NULL
    );
    """,
]


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    current = int(row[0]) if row else 0
    for version, sql in enumerate(_MIGRATIONS, start=1):
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()
