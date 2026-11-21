from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
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

    async def upsert_tour_from_list(
        self,
        item: TourListItem,
        now_iso: Optional[str] = None,
        trip_id: Optional[str] = None,
        destination_country: Optional[str] = None,
        destination_airport: Optional[str] = None,
    ) -> str:
        now = now_iso or datetime.now(timezone.utc).isoformat()
        tour_uid = self.build_tour_uid(item.agency, item.tour_code, item.departure_date)
        effective_trip_id = trip_id or getattr(item, "trip_id", "default") or "default"

        query = """
        INSERT INTO tours (
            tour_uid, trip_id, destination_country, destination_airport,
            agency, tour_code, tour_name, departure_date,
            days, departure_airport, detail_url, first_seen_at, last_seen_at, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(tour_uid) DO UPDATE SET
            trip_id = CASE
                WHEN excluded.trip_id != 'default' THEN excluded.trip_id
                ELSE tours.trip_id
            END,
            destination_country = COALESCE(excluded.destination_country, tours.destination_country),
            destination_airport = COALESCE(excluded.destination_airport, tours.destination_airport),
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
                    effective_trip_id,
                    destination_country,
                    destination_airport,
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

    async def update_tour_evaluation(
        self, tour_uid: str, score: float, tags: List[str]
    ) -> bool:
        tags_json = json.dumps(tags, ensure_ascii=False)
        query = """
        UPDATE tours
        SET score = ?, tags_json = ?
        WHERE tour_uid = ?
        """
        async with self.get_connection() as db:
            cursor = await db.execute(query, (score, tags_json, tour_uid))
            await db.commit()
            return cursor.rowcount > 0

    async def get_tour(self, tour_uid: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM tours WHERE tour_uid = ?"
        async with self.get_connection() as db:
            async with db.execute(query, (tour_uid,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_active_tours(self, trip_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if trip_id:
            query = "SELECT * FROM tours WHERE is_active = 1 AND trip_id = ? ORDER BY departure_date ASC"
            params: tuple[Any, ...] = (trip_id,)
        else:
            query = "SELECT * FROM tours WHERE is_active = 1 ORDER BY departure_date ASC"
            params = ()
        async with self.get_connection() as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_tours_needing_detail_parsing(
        self, max_age_days: int = 7, limit: int = 15, trip_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if trip_id:
            query = """
            SELECT * FROM tours
            WHERE is_active = 1
              AND trip_id = ?
              AND (
                  detail_parsed_at IS NULL
                  OR julianday('now') - julianday(detail_parsed_at) > ?
              )
            ORDER BY departure_date ASC
            LIMIT ?;
            """
            params: tuple[Any, ...] = (trip_id, max_age_days, limit)
        else:
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
            params = (max_age_days, limit)
        async with self.get_connection() as db:
            async with db.execute(query, params) as cursor:
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

    async def insert_price_snapshot_if_changed(
        self,
        tour_uid: str,
        adult_price: Optional[int],
        seats_available: Optional[int],
        status: Optional[str],
        estimated_family_total: Optional[int],
        captured_at: Optional[str] = None,
    ) -> Tuple[bool, int]:
        """事件驅動快照寫入：僅在首次出現或價格、機位、狀態任一欄位變動時寫入。"""
        latest = await self.get_latest_snapshot(tour_uid)
        if latest is not None:
            if (
                latest.get("adult_price") == adult_price
                and latest.get("seats_available") == seats_available
                and latest.get("status") == status
                and latest.get("estimated_family_total") == estimated_family_total
            ):
                return False, int(latest["id"])

        row_id = await self.insert_price_snapshot(
            tour_uid=tour_uid,
            adult_price=adult_price,
            seats_available=seats_available,
            status=status,
            estimated_family_total=estimated_family_total,
            captured_at=captured_at,
        )
        return True, row_id

    async def get_latest_snapshot(self, tour_uid: str) -> Optional[Dict[str, Any]]:
        query = """
        SELECT * FROM price_snapshots
        WHERE tour_uid = ?
        ORDER BY captured_at DESC, id DESC
        LIMIT 1;
        """
        async with self.get_connection() as db:
            async with db.execute(query, (tour_uid,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_last_snapshot_time(self) -> Optional[str]:
        query = "SELECT MAX(captured_at) AS last_run_at FROM price_snapshots;"
        async with self.get_connection() as db:
            async with db.execute(query) as cursor:
                row = await cursor.fetchone()
                return row["last_run_at"] if row and row["last_run_at"] else None

    async def check_connection(self) -> bool:
        try:
            async with self.get_connection() as db:
                async with db.execute("SELECT 1;") as cursor:
                    row = await cursor.fetchone()
                    return row is not None
        except Exception:
            return False

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

    async def insert_scan_history(
        self,
        trip_id: str,
        agencies_run: List[str] | str,
        total_found: int = 0,
        new_count: int = 0,
        price_drop_count: int = 0,
        seats_released_count: int = 0,
        status_change_count: int = 0,
        error_summary: Optional[str] = None,
        cli_args: Optional[Dict[str, Any]] = None,
        scanned_at: Optional[str] = None,
    ) -> int:
        now = scanned_at or datetime.now(timezone.utc).isoformat()
        agencies_str = (
            json.dumps(agencies_run, ensure_ascii=False)
            if isinstance(agencies_run, list)
            else str(agencies_run)
        )
        args_json = json.dumps(cli_args or {}, ensure_ascii=False)
        query = """
        INSERT INTO scan_history (
            trip_id, scanned_at, agencies_run, total_found,
            new_count, price_drop_count, seats_released_count,
            status_change_count, error_summary, cli_args_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        async with self.get_connection() as db:
            cursor = await db.execute(
                query,
                (
                    trip_id,
                    now,
                    agencies_str,
                    total_found,
                    new_count,
                    price_drop_count,
                    seats_released_count,
                    status_change_count,
                    error_summary,
                    args_json,
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_recent_scan_history(
        self, trip_id: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        if trip_id:
            query = """
            SELECT * FROM scan_history
            WHERE trip_id = ?
            ORDER BY scanned_at DESC, id DESC
            LIMIT ?;
            """
            params: tuple[Any, ...] = (trip_id, limit)
        else:
            query = """
            SELECT * FROM scan_history
            ORDER BY scanned_at DESC, id DESC
            LIMIT ?;
            """
            params = (limit,)
        async with self.get_connection() as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_recent_snapshot_diffs(
        self, hours: int = 24, trip_id: Optional[str] = None, limit: int = 30
    ) -> List[Dict[str, Any]]:
        """利用視窗函式查詢指定小時內的新團上架、價格與機位狀態異動紀錄。"""
        offset = f"-{abs(int(hours))} hours"
        trip_filter = "AND trip_id = ?" if trip_id else ""
        query = f"""
        WITH ordered AS (
            SELECT
                ps.id,
                ps.tour_uid,
                ps.captured_at,
                ps.adult_price AS new_price,
                LAG(ps.adult_price) OVER (
                    PARTITION BY ps.tour_uid ORDER BY ps.captured_at ASC, ps.id ASC
                ) AS old_price,
                ps.seats_available AS new_seats,
                LAG(ps.seats_available) OVER (
                    PARTITION BY ps.tour_uid ORDER BY ps.captured_at ASC, ps.id ASC
                ) AS old_seats,
                ps.status AS new_status,
                LAG(ps.status) OVER (
                    PARTITION BY ps.tour_uid ORDER BY ps.captured_at ASC, ps.id ASC
                ) AS old_status,
                ps.estimated_family_total AS new_family_total,
                LAG(ps.estimated_family_total) OVER (
                    PARTITION BY ps.tour_uid ORDER BY ps.captured_at ASC, ps.id ASC
                ) AS old_family_total,
                t.trip_id,
                t.agency,
                t.tour_name,
                t.departure_date
            FROM price_snapshots ps
            JOIN tours t ON ps.tour_uid = t.tour_uid
        )
        SELECT * FROM ordered
        WHERE julianday(captured_at) >= julianday('now', ?)
          {trip_filter}
          AND (
            old_status IS NULL
            OR old_price IS NOT new_price
            OR old_seats IS NOT new_seats
            OR old_status IS NOT new_status
            OR old_family_total IS NOT new_family_total
          )
        ORDER BY captured_at DESC, id DESC
        LIMIT ?;
        """
        params: List[Any] = [offset]
        if trip_id:
            params.append(trip_id)
        params.append(limit)
        async with self.get_connection() as db:
            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
