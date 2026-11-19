import os
import sqlite3
from pathlib import Path
import aiosqlite

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "data/tracker.db")

DDL_STATEMENTS = """
CREATE TABLE IF NOT EXISTS tours (
    tour_uid TEXT PRIMARY KEY,
    agency TEXT NOT NULL,
    tour_code TEXT NOT NULL,
    tour_name TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    days INTEGER NOT NULL,
    departure_airport TEXT,
    detail_url TEXT NOT NULL,
    detail_json TEXT,
    detail_parsed_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tour_uid TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    adult_price INTEGER,
    seats_available INTEGER,
    status TEXT,
    estimated_family_total INTEGER,
    FOREIGN KEY (tour_uid) REFERENCES tours(tour_uid)
);

CREATE TABLE IF NOT EXISTS flight_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    return_date TEXT NOT NULL,
    min_price_twd INTEGER,
    median_price_twd INTEGER,
    raw_json TEXT,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT UNIQUE NOT NULL,
    alert_type TEXT NOT NULL,
    tour_uid TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_tour_captured ON price_snapshots(tour_uid, captured_at);
CREATE INDEX IF NOT EXISTS idx_alert_logs_key ON alert_logs(alert_key);
CREATE INDEX IF NOT EXISTS idx_flight_benchmarks_route ON flight_benchmarks(origin, destination, depart_date);
"""


def get_db_path(custom_path: str | None = None) -> str:
    path = custom_path or DEFAULT_DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db_sync(db_path: str | None = None) -> None:
    path = get_db_path(db_path)
    with sqlite3.connect(path) as conn:
        conn.executescript(DDL_STATEMENTS)
        conn.commit()


async def init_db(db_path: str | None = None) -> None:
    path = get_db_path(db_path)
    async with aiosqlite.connect(path) as db:
        await db.executescript(DDL_STATEMENTS)
        await db.commit()
