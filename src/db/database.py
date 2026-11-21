from contextlib import closing
import os
import sqlite3
from pathlib import Path
from typing import Set
import aiosqlite

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "data/radar.db")

BASE_DDL_STATEMENTS = """
CREATE TABLE IF NOT EXISTS tours (
    tour_uid TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL DEFAULT 'default',
    destination_country TEXT,
    destination_airport TEXT,
    agency TEXT NOT NULL,
    tour_code TEXT NOT NULL,
    tour_name TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    days INTEGER NOT NULL,
    departure_airport TEXT,
    detail_url TEXT NOT NULL,
    detail_json TEXT,
    detail_parsed_at TEXT,
    score REAL DEFAULT 0,
    tags_json TEXT,
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

CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    agencies_run TEXT,
    total_found INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    price_drop_count INTEGER DEFAULT 0,
    seats_released_count INTEGER DEFAULT 0,
    status_change_count INTEGER DEFAULT 0,
    error_summary TEXT,
    cli_args_json TEXT
);
"""

INDEX_DDL_STATEMENTS = """
CREATE INDEX IF NOT EXISTS idx_tours_trip_id ON tours(trip_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_tour_captured ON price_snapshots(tour_uid, captured_at);
CREATE INDEX IF NOT EXISTS idx_alert_logs_key ON alert_logs(alert_key);
CREATE INDEX IF NOT EXISTS idx_flight_benchmarks_route ON flight_benchmarks(origin, destination, depart_date);
CREATE INDEX IF NOT EXISTS idx_scan_history_trip_time ON scan_history(trip_id, scanned_at);
"""

TOURS_MIGRATION_COLUMNS = [
    ("trip_id", "TEXT NOT NULL DEFAULT 'default'"),
    ("destination_country", "TEXT"),
    ("destination_airport", "TEXT"),
    ("score", "REAL DEFAULT 0"),
    ("tags_json", "TEXT"),
]


def get_db_path(custom_path: str | None = None) -> str:
    path = custom_path or os.getenv("DATABASE_PATH") or DEFAULT_DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _remove_db_files(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(f"{path}{suffix}")
        if p.exists():
            p.unlink()


def _migrate_tours_sync(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(tours);")
    existing_cols: Set[str] = {row[1] for row in cursor.fetchall()}
    had_no_trip_id = "trip_id" not in existing_cols

    for col_name, col_def in TOURS_MIGRATION_COLUMNS:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE tours ADD COLUMN {col_name} {col_def};")

    if had_no_trip_id:
        conn.execute(
            "UPDATE tours SET trip_id = 'okinawa_lny2027' WHERE trip_id = 'default' OR trip_id IS NULL;"
        )


async def _migrate_tours_async(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(tours);") as cursor:
        rows = await cursor.fetchall()
    existing_cols: Set[str] = {row[1] for row in rows}
    had_no_trip_id = "trip_id" not in existing_cols

    for col_name, col_def in TOURS_MIGRATION_COLUMNS:
        if col_name not in existing_cols:
            await db.execute(f"ALTER TABLE tours ADD COLUMN {col_name} {col_def};")

    if had_no_trip_id:
        await db.execute(
            "UPDATE tours SET trip_id = 'okinawa_lny2027' WHERE trip_id = 'default' OR trip_id IS NULL;"
        )


def init_db_sync(db_path: str | None = None, force: bool = False) -> None:
    path = get_db_path(db_path)
    if force:
        _remove_db_files(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(BASE_DDL_STATEMENTS)
        _migrate_tours_sync(conn)
        conn.executescript(INDEX_DDL_STATEMENTS)
        conn.commit()


async def init_db(db_path: str | None = None, force: bool = False) -> None:
    path = get_db_path(db_path)
    if force:
        _remove_db_files(path)
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executescript(BASE_DDL_STATEMENTS)
        await _migrate_tours_async(db)
        await db.executescript(INDEX_DDL_STATEMENTS)
        await db.commit()


def checkpoint_db_sync(db_path: str | None = None) -> None:
    """將 WAL 異動合併回主資料庫檔並清理輔助檔，確保 Git Commit 完整無漏。"""
    path = get_db_path(db_path)
    if not Path(path).exists():
        return
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        try:
            conn.execute("PRAGMA journal_mode=DELETE;")
        except sqlite3.OperationalError:
            pass
        conn.commit()


async def checkpoint_db(db_path: str | None = None) -> None:
    """非同步將 WAL 異動合併回主資料庫檔。"""
    path = get_db_path(db_path)
    if not Path(path).exists():
        return
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        try:
            await db.execute("PRAGMA journal_mode=DELETE;")
        except Exception:
            pass
        await db.commit()
