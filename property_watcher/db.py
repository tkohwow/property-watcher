import sqlite3
from pathlib import Path
from typing import Optional, Iterable

from .models import Snapshot


SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    url TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    memo TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 旧版互換用。旧DBに snapshots が残っていても読み取りだけできるように残す。
-- 新規データはこのテーブルには追加せず、latest_snapshots に上書き保存する。
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    status_code INTEGER,
    final_url TEXT,
    title TEXT,
    price INTEGER,
    status_text TEXT,
    contact_available INTEGER,
    content_hash TEXT NOT NULL,
    error TEXT,
    FOREIGN KEY(url) REFERENCES targets(url)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_url_id ON snapshots(url, id);

-- URLごとに「最後に取得した状態」だけを保持するテーブル。
CREATE TABLE IF NOT EXISTS latest_snapshots (
    url TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    status_code INTEGER,
    final_url TEXT,
    title TEXT,
    price INTEGER,
    status_text TEXT,
    contact_available INTEGER,
    content_hash TEXT NOT NULL,
    raw_text TEXT,
    error TEXT,
    FOREIGN KEY(url) REFERENCES targets(url)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    FOREIGN KEY(url) REFERENCES targets(url)
);

CREATE INDEX IF NOT EXISTS idx_events_url_id ON events(url, id);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_target(conn: sqlite3.Connection, url: str, name: str, memo: str = "") -> None:
    conn.execute(
        """
        INSERT INTO targets(url, name, memo)
        VALUES (?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            name = excluded.name,
            memo = excluded.memo,
            updated_at = CURRENT_TIMESTAMP
        """,
        (url, name, memo),
    )


def upsert_latest_snapshot(conn: sqlite3.Connection, snapshot: Snapshot) -> None:
    conn.execute(
        """
        INSERT INTO latest_snapshots(
            url, fetched_at, ok, status_code, final_url, title, price,
            status_text, contact_available, content_hash, raw_text, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            fetched_at = excluded.fetched_at,
            ok = excluded.ok,
            status_code = excluded.status_code,
            final_url = excluded.final_url,
            title = excluded.title,
            price = excluded.price,
            status_text = excluded.status_text,
            contact_available = excluded.contact_available,
            content_hash = excluded.content_hash,
            raw_text = excluded.raw_text,
            error = excluded.error
        """,
        (
            snapshot.url,
            snapshot.fetched_at,
            int(snapshot.ok),
            snapshot.status_code,
            snapshot.final_url,
            snapshot.title,
            snapshot.price,
            snapshot.status_text,
            None if snapshot.contact_available is None else int(snapshot.contact_available),
            snapshot.content_hash,
            snapshot.raw_text,
            snapshot.error,
        ),
    )


def get_latest_snapshot(conn: sqlite3.Connection, url: str) -> Optional[sqlite3.Row]:
    latest = conn.execute(
        "SELECT * FROM latest_snapshots WHERE url = ? LIMIT 1",
        (url,),
    ).fetchone()
    if latest is not None:
        return latest

    # 旧版DBから移行した直後でも、前回値との差分比較ができるようにフォールバックする。
    return conn.execute(
        "SELECT * FROM snapshots WHERE url = ? ORDER BY id DESC LIMIT 1",
        (url,),
    ).fetchone()


def insert_events(conn: sqlite3.Connection, events: Iterable[dict]) -> None:
    conn.executemany(
        """
        INSERT INTO events(url, occurred_at, severity, event_type, message, old_value, new_value)
        VALUES (:url, :occurred_at, :severity, :event_type, :message, :old_value, :new_value)
        """,
        list(events),
    )
