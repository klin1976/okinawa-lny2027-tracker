from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
import aiosqlite

from src.db.database import get_db_path
from src.schemas.discovery_schema import TourListItem


class TourRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = get_db_path(db_path)

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    @staticmethod
    def build_tour_uid(agency: str, tour_code: str, departure_date: str) -> str:
        return f"{agency}:{tour_code}:{departure_date}"

    async def upsert_tour_from_list(self, item: TourListItem, now_iso: Optional[str] = None) -> str:
        now = now_iso or datetime.now(timezone.utc).isoformat()
        tour_uid = self.build_tour_uid(item.agency, item.tour_code, item.departure_date)

        query = """
        INSERT INTO tours (
            tour_uid, agency, tour_code, tour_name, departure_date,
            days, departure_airport, detail_url, first_seen_at, last_seen_at, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(tour_uid) DO UPDATE SET
            tour_name = excluded.tour_name,
            departure_date = excluded.departure_date,
            days = excluded.days,
            departure_airport = excluded.departure_airport,
            detail_url = excluded.detail_url,
            last_seen_at = excluded.last_seen_at,
            is_active = 1;
        """
        async with self.get_connection() as db:
            await db.execute(
                query,
                (
                    tour_uid,
                    item.agency,
                    item.tour_code,
                    item.tour_name,
                    item.departure_date,
                    item.days,
                    item.departure_airport,
                    item.detail_url,
                    now,
                    now,
                ),
            )
            await db.commit()
        return tour_uid

    async def update_tour_detail(
        self, tour_uid: str, detail_json: str, parsed_at_iso: Optional[str] = None
    ) -> bool:
        now = parsed_at_iso or datetime.now(timezone.utc).isoformat()
        query = """
        UPDATE tours
        SET detail_json = ?, detail_parsed_at = ?
        WHERE tour_uid = ?
        """
        async with self.get_connection() as db:
            cursor = await db.execute(query, (detail_json, now, tour_uid))
            await db.commit()
            return cursor.rowcount > 0

    async def get_tour(self, tour_uid: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM tours WHERE tour_uid = ?"
        async with self.get_connection() as db:
            async with db.execute(query, (tour_uid,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_active_tours(self) -> List[Dict[str, Any]]:
        query = "SELECT * FROM tours WHERE is_active = 1 ORDER BY departure_date ASC"
        async with self.get_connection() as db:
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_tours_needing_detail_parsing(
        self, max_age_days: int = 7, limit: int = 15
    ) -> List[Dict[str, Any]]:
        query = """
        SELECT * FROM tours
        WHERE is_active = 1
          AND (
              detail_parsed_at IS NULL
              OR julianday('now') - julianday(detail_parsed_at) > ?
          )
        ORDER BY departure_date ASC
        LIMIT ?;
        """
        async with self.get_connection() as db:
            async with db.execute(query, (max_age_days, limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def insert_price_snapshot(
        self,
        tour_uid: str,
        adult_price: Optional[int],
        seats_available: Optional[int],
        status: Optional[str],
        estimated_family_total: Optional[int],
        captured_at: Optional[str] = None,
    ) -> int:
        now = captured_at or datetime.now(timezone.utc).isoformat()
        query = """
        INSERT INTO price_snapshots (
            tour_uid, captured_at, adult_price, seats_available, status, estimated_family_total
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        async with self.get_connection() as db:
            cursor = await db.execute(
                query,
                (tour_uid, now, adult_price, seats_available, status, estimated_family_total),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_latest_two_snapshots(self, tour_uid: str) -> List[Dict[str, Any]]:
        query = """
        SELECT * FROM price_snapshots
        WHERE tour_uid = ?
        ORDER BY captured_at DESC, id DESC
        LIMIT 2;
        """
        async with self.get_connection() as db:
            async with db.execute(query, (tour_uid,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_snapshots_history(self, tour_uid: str) -> List[Dict[str, Any]]:
        query = """
        SELECT * FROM price_snapshots
        WHERE tour_uid = ?
        ORDER BY captured_at ASC, id ASC;
        """
        async with self.get_connection() as db:
            async with db.execute(query, (tour_uid,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def is_alert_logged(self, alert_key: str) -> bool:
        query = "SELECT 1 FROM alert_logs WHERE alert_key = ? LIMIT 1;"
        async with self.get_connection() as db:
            async with db.execute(query, (alert_key,)) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def insert_alert_log(
        self,
        alert_key: str,
        alert_type: str,
        tour_uid: Optional[str],
        message: str,
        created_at: Optional[str] = None,
    ) -> int:
        now = created_at or datetime.now(timezone.utc).isoformat()
        query = """
        INSERT INTO alert_logs (alert_key, alert_type, tour_uid, message, created_at)
        VALUES (?, ?, ?, ?, ?)
        """
        async with self.get_connection() as db:
            cursor = await db.execute(query, (alert_key, alert_type, tour_uid, message, now))
            await db.commit()
            return cursor.lastrowid or 0

    async def insert_flight_benchmark(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
        min_price_twd: int,
        median_price_twd: int,
        raw_json: str,
        captured_at: Optional[str] = None,
    ) -> int:
        now = captured_at or datetime.now(timezone.utc).isoformat()
        query = """
        INSERT INTO flight_benchmarks (
            origin, destination, depart_date, return_date,
            min_price_twd, median_price_twd, raw_json, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        async with self.get_connection() as db:
            cursor = await db.execute(
                query,
                (
                    origin,
                    destination,
                    depart_date,
                    return_date,
                    min_price_twd,
                    median_price_twd,
                    raw_json,
                    now,
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_latest_flight_benchmark(
        self, origin: str, destination: str, depart_date: str
    ) -> Optional[Dict[str, Any]]:
        query = """
        SELECT * FROM flight_benchmarks
        WHERE origin = ? AND destination = ? AND depart_date = ?
        ORDER BY captured_at DESC, id DESC
        LIMIT 1;
        """
        async with self.get_connection() as db:
            async with db.execute(query, (origin, destination, depart_date)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
