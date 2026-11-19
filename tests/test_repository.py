import os
import pytest
from src.db.database import init_db
from src.db.repository import TourRepository
from src.schemas.discovery_schema import TourListItem


@pytest.fixture
async def temp_repo(tmp_path):
    db_file = str(tmp_path / "test_tracker.db")
    await init_db(db_file)
    repo = TourRepository(db_file)
    return repo


@pytest.mark.asyncio
async def test_repository_tour_upsert_and_snapshots(temp_repo):
    item = TourListItem(
        agency="雄獅旅遊",
        tour_code="27JN01",
        tour_name="沖繩新春五日",
        departure_date="2027-02-05",
        days=5,
        departure_airport="TPE",
        adult_price=48000,
        seats_available=15,
        status="可報名",
        detail_url="https://travel.liontravel.com/detail?Prod=27JN01",
    )

    tour_uid = await temp_repo.upsert_tour_from_list(item)
    assert tour_uid == "雄獅旅遊:27JN01:2027-02-05"

    tour = await temp_repo.get_tour(tour_uid)
    assert tour is not None
    assert tour["tour_name"] == "沖繩新春五日"
    assert tour["is_active"] == 1

    # 寫入第一筆快照
    snap1_id = await temp_repo.insert_price_snapshot(
        tour_uid=tour_uid,
        adult_price=48000,
        seats_available=15,
        status="可報名",
        estimated_family_total=480000,
        captured_at="2027-01-01T09:00:00Z",
    )
    assert snap1_id > 0

    # 寫入第二筆快照 (降價)
    snap2_id = await temp_repo.insert_price_snapshot(
        tour_uid=tour_uid,
        adult_price=45000,
        seats_available=12,
        status="可報名",
        estimated_family_total=450000,
        captured_at="2027-01-02T09:00:00Z",
    )
    assert snap2_id > 0

    # 取得最新兩筆快照
    snaps = await temp_repo.get_latest_two_snapshots(tour_uid)
    assert len(snaps) == 2
    assert snaps[0]["adult_price"] == 45000
    assert snaps[1]["adult_price"] == 48000


@pytest.mark.asyncio
async def test_repository_alert_log(temp_repo):
    key = "PRICE_DROP:雄獅:01:45000"
    assert not await temp_repo.is_alert_logged(key)

    await temp_repo.insert_alert_log(
        alert_key=key,
        alert_type="PRICE_DROP",
        tour_uid="雄獅:01:2027-02-05",
        message="價格下跌 3,000 元",
    )

    assert await temp_repo.is_alert_logged(key)
