from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import cli
from src.db.database import checkpoint_db_sync, init_db
from src.db.repository import TourRepository
from src.schemas.discovery_schema import TourListItem


@pytest.mark.asyncio
async def test_legacy_sqlite_migration_and_event_driven_snapshots(tmp_path):
    db_file = str(tmp_path / "legacy_tracker.db")

    # 建立舊版不含 trip_id / score / scan_history 的資料庫並塞入舊資料
    with sqlite3.connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE tours (
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
            INSERT INTO tours (
                tour_uid, agency, tour_code, tour_name, departure_date,
                days, departure_airport, detail_url, first_seen_at, last_seen_at
            ) VALUES (
                '雄獅旅遊:LEGACY01:2027-02-04', '雄獅旅遊', 'LEGACY01', '舊版沖繩五日',
                '2027-02-04', 5, 'TPE', 'https://example.com/legacy',
                '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z'
            );
            """
        )

    # 執行 init_db 自動遷移
    await init_db(db_file)
    repo = TourRepository(db_file)

    migrated = await repo.get_tour("雄獅旅遊:LEGACY01:2027-02-04")
    assert migrated is not None
    assert migrated["trip_id"] == "okinawa_lny2027"
    assert "score" in migrated

    # 驗證事件驅動快照：完全相同數值不重複寫入
    item = TourListItem(
        trip_id="korea_spring2027",
        agency="山富旅遊",
        tour_code="KR001",
        tour_name="韓國首爾五日",
        departure_date="2027-04-02",
        days=5,
        departure_airport="TPE",
        adult_price=25900,
        seats_available=15,
        status="可報名",
        detail_url="https://example.com/kr001",
    )
    uid = await repo.upsert_tour_from_list(
        item, trip_id="korea_spring2027", destination_country="韓國", destination_airport="ICN"
    )

    inserted1, _ = await repo.insert_price_snapshot_if_changed(uid, 25900, 15, "可報名", 260000)
    inserted2, _ = await repo.insert_price_snapshot_if_changed(uid, 25900, 15, "可報名", 260000)
    inserted3, _ = await repo.insert_price_snapshot_if_changed(uid, 23900, 15, "保證出團", 240000)

    assert inserted1 is True
    assert inserted2 is False
    assert inserted3 is True
    history = await repo.get_snapshots_history(uid)
    assert len(history) == 2

    # 寫入 scan_history 並查詢近期 diffs
    await repo.insert_scan_history(
        trip_id="korea_spring2027",
        agencies_run=["山富旅遊"],
        total_found=1,
        new_count=1,
        price_drop_count=1,
    )
    scans = await repo.get_recent_scan_history(trip_id="korea_spring2027")
    assert len(scans) == 1
    assert scans[0]["price_drop_count"] == 1

    diffs = await repo.get_recent_snapshot_diffs(hours=24, trip_id="korea_spring2027")
    assert len(diffs) >= 1

    checkpoint_db_sync(db_file)


def test_cli_init_db_list_trips_diff_and_scan(tmp_path):
    db_file = str(tmp_path / "cli_radar.db")

    assert cli.main(["list-trips"]) == 0
    assert cli.main(["init-db", "--db-path", db_file]) == 0
    assert cli.main(["diff", "--db-path", db_file]) == 0

    fake_result = {
        "run_id": "20261121T140000Z",
        "trip_id": "okinawa_lny2027",
        "trip_name": "2027 春節沖繩家族團",
        "status": "SUCCESS",
        "stats": {
            "total_discovered": 0,
            "snapshots_inserted": 0,
            "llm_calls_used": 0,
            "llm_skipped_cached": 0,
            "alerts_count": 0,
            "agencies": {"雄獅旅遊": {"count": 0, "status": "OK"}},
            "flight_benchmarks_twd": {},
        },
        "diff_summary": {"new_count": 0, "price_drop_count": 0, "seats_released_count": 0},
        "alerts": [],
        "top_5_rankings": [],
        "rankings": [],
        "errors": [],
    }

    with patch(
        "src.services.pipeline_service.PipelineService.run_daily_pipeline",
        new=AsyncMock(return_value=fake_result),
    ) as mock_run, patch("src.cli.send_webhook_digest") as mock_digest:
        rc = cli.main(
            [
                "scan",
                "--trip",
                "okinawa_lny2027",
                "--skip-llm",
                "--skip-flights",
                "--no-playwright",
                "--notify",
                "--digest",
                "--db-path",
                db_file,
            ]
        )

    assert rc == 0
    assert mock_run.await_count == 1
    assert mock_run.await_args.kwargs["skip_llm"] is True
    assert mock_run.await_args.kwargs["skip_flight_benchmark"] is True
    mock_digest.assert_called_once()
