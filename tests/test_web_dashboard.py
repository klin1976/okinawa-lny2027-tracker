from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src import cli
from src.config import get_settings
from src.db.database import init_db
from src.db.repository import TourRepository
from src.main import app
from src.schemas.discovery_schema import TourListItem
from src.web.catalog import (
    build_destination_catalog,
    build_dynamic_trip_config,
    build_party_members,
)
from src.web.exporter import build_dashboard_payload, export_dashboard_json


async def _seed_sample_db(db_path: str) -> str:
    await init_db(db_path)
    repo = TourRepository(db_path)

    item = TourListItem(
        trip_id="okinawa_lny2027",
        agency="雄獅旅遊",
        tour_code="OKAWEB01",
        tour_name="沖繩海景連住無購物四日",
        departure_date="2027-02-05",
        days=4,
        departure_airport="TPE",
        adult_price=32900,
        seats_available=16,
        status="保證出團",
        detail_url="https://travel.liontravel.com/detail?NormGroupID=OKAWEB01",
    )
    uid = await repo.upsert_tour_from_list(
        item,
        trip_id="okinawa_lny2027",
        destination_country="日本",
        destination_airport="OKA",
    )
    now1 = "2026-11-24T01:00:00+00:00"
    now2 = datetime.now(timezone.utc).isoformat()
    await repo.insert_price_snapshot(uid, 34900, 12, "可報名", 340000, captured_at=now1)
    await repo.insert_price_snapshot(uid, 32900, 16, "保證出團", 320000, captured_at=now2)
    await repo.insert_scan_history(
        trip_id="okinawa_lny2027",
        agencies_run=["雄獅旅遊"],
        total_found=1,
        new_count=1,
        price_drop_count=1,
    )
    return uid


@pytest.mark.asyncio
async def test_get_all_snapshots_grouped(tmp_path):
    db_file = str(tmp_path / "grouped_test.db")
    uid = await _seed_sample_db(db_file)
    repo = TourRepository(db_file)

    assert await repo.get_all_snapshots_grouped([]) == {}

    all_grouped = await repo.get_all_snapshots_grouped()
    assert uid in all_grouped
    assert len(all_grouped[uid]) == 2
    assert all_grouped[uid][0]["adult_price"] == 34900
    assert all_grouped[uid][1]["adult_price"] == 32900

    filtered = await repo.get_all_snapshots_grouped([uid, "nonexistent"])
    assert list(filtered.keys()) == [uid]
    assert len(filtered[uid]) == 2


@pytest.mark.asyncio
async def test_build_and_export_dashboard_json(tmp_path):
    db_file = str(tmp_path / "export_test.db")
    uid = await _seed_sample_db(db_file)
    out_file = tmp_path / "web" / "data" / "dashboard.json"

    payload = await build_dashboard_payload(db_path=db_file, trips_dir="config/trips")
    assert payload["summary"]["total_active_tours"] == 1
    assert payload["summary"]["trips_count"] >= 1
    assert len(payload["tours"]) == 1

    tour = payload["tours"][0]
    assert tour["tour_uid"] == uid
    assert tour["adult_price"] == 32900
    assert tour["budget"]["grand_total_twd"] > 0
    assert len(tour["budget"]["breakdown"]["items"]) >= 1
    assert len(tour["snapshots"]) == 2
    assert "has_shopping_station" in tour
    assert len(payload["scan_history"]) == 1
    assert len(payload["recent_diffs"]) >= 1

    summary = await export_dashboard_json(
        output_path=out_file, db_path=db_file, trips_dir="config/trips"
    )
    assert out_file.exists()
    assert summary["total_active_tours"] == 1

    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert written["tours"][0]["tour_uid"] == uid


@pytest.mark.asyncio
async def test_fastapi_web_static_and_dashboard_endpoint(tmp_path, monkeypatch):
    db_file = tmp_path / "web_api_test.db"
    uid = await _seed_sample_db(str(db_file))

    monkeypatch.setenv("API_KEY", "web-secret-test")
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    get_settings.cache_clear()

    try:
        with TestClient(app) as client:
            # 1. Static root serves index.html
            root_resp = client.get("/")
            assert root_resp.status_code == 200
            assert "Travel Radar" in root_resp.text

            # 2. Unauthenticated GET /api/v1/dashboard returns 200 JSON
            dash_resp = client.get("/api/v1/dashboard")
            assert dash_resp.status_code == 200
            body = dash_resp.json()
            assert body["summary"]["total_active_tours"] == 1
            assert body["tours"][0]["tour_uid"] == uid

            # 3. Protected POST /api/v1/pipeline/daily-run still requires X-API-Key
            unauth_resp = client.post("/api/v1/pipeline/daily-run", json={})
            assert unauth_resp.status_code == 401
    finally:
        get_settings.cache_clear()


def test_cli_build_web_command(tmp_path):
    db_file = str(tmp_path / "cli_web.db")
    out_file = tmp_path / "out_dashboard.json"

    assert cli.main(["init-db", "--db-path", db_file]) == 0
    exit_code = cli.main(
        [
            "build-web",
            "--db-path",
            db_file,
            "--output",
            str(out_file),
        ]
    )
    assert exit_code == 0
    assert out_file.exists()

    parsed = json.loads(out_file.read_text(encoding="utf-8"))
    assert "trips" in parsed
    assert "tours" in parsed
    assert "summary" in parsed
    assert "destinations_catalog" in parsed
    assert "default_party" in parsed


@pytest.mark.asyncio
async def test_dashboard_payload_includes_catalog_party_and_pricing_params(tmp_path):
    db_file = str(tmp_path / "catalog_payload.db")
    await _seed_sample_db(db_file)

    payload = await build_dashboard_payload(db_path=db_file, trips_dir="config/trips")
    assert len(payload["destinations_catalog"]) >= 5
    japan_group = next(
        (g for g in payload["destinations_catalog"] if g["country"] == "日本"), None
    )
    assert japan_group is not None
    okinawa = next(
        (r for r in japan_group["regions"] if r["region_name"] == "沖繩"), None
    )
    assert okinawa is not None
    assert "okinawa_lny2027" in okinawa["trip_ids"]

    dp = payload["default_party"]
    assert dp["adults"] >= 1
    assert dp["total"] == (
        dp["adults"] + dp["children_with_bed"] + dp["children_no_bed"] + dp["infants"]
    )

    tour = payload["tours"][0]
    assert tour["destination_country"] == "日本"
    assert tour["destination_region"] == "沖繩"
    assert tour["pricing_params"]["adult_twin_price"] == 32900
    assert "default_tip_per_day" in tour["pricing_params"]


def test_build_dynamic_trip_config_and_catalog(tmp_path):
    trip_cfg = build_dynamic_trip_config(
        country="日本",
        region_name="九州",
        departure_date_start="2027-04-01",
        departure_date_end="2027-04-10",
        min_days=5,
        max_days=6,
        adults=2,
        children_with_bed=1,
        children_no_bed=1,
        infants=1,
        save_as_trip=True,
        trips_dir=tmp_path,
    )
    assert trip_cfg.trip_id == "custom_kyushu"
    assert trip_cfg.destination.country == "日本"
    assert trip_cfg.destination.region_name == "九州"
    assert "福岡" in trip_cfg.destination.search_keywords
    assert trip_cfg.party.members is not None
    assert len(trip_cfg.party.members) == 4
    assert (tmp_path / "custom_kyushu.yaml").exists()

    catalog = build_destination_catalog([trip_cfg])
    kyushu = next(
        r
        for g in catalog
        if g["country"] == "日本"
        for r in g["regions"]
        if r["region_name"] == "九州"
    )
    assert "custom_kyushu" in kyushu["trip_ids"]

    members = build_party_members(adults=2, children_with_bed=1, children_no_bed=1)
    assert sum(m["count"] for m in members) == 4


def test_api_daily_run_with_dynamic_destination_and_party(tmp_path, monkeypatch):
    db_file = tmp_path / "dynamic_run.db"
    monkeypatch.setenv("API_KEY", "dyn-secret")
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    get_settings.cache_clear()

    captured = {}

    class FakePipelineService:
        def __init__(self, settings, trip_config=None, **_kwargs):
            captured["trip_config"] = trip_config

        async def run_daily_pipeline(
            self,
            agencies=None,
            force_reparse=False,
            max_new_details_per_run=None,
            skip_flight_benchmark=False,
        ):
            captured["skip_flight_benchmark"] = skip_flight_benchmark
            return {"status": "ok", "stats": {"total_discovered": 0}}

    monkeypatch.setattr("src.main.PipelineService", FakePipelineService)

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/pipeline/daily-run",
                headers={"X-API-Key": "dyn-secret"},
                json={
                    "country": "日本",
                    "region_name": "九州",
                    "adults": 2,
                    "children_with_bed": 1,
                    "children_no_bed": 1,
                    "skip_flight_benchmark": True,
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
            cfg = captured["trip_config"]
            assert cfg is not None
            assert cfg.destination.country == "日本"
            assert cfg.destination.region_name == "九州"
            assert sum(m["count"] for m in cfg.party.members) == 4
            assert captured["skip_flight_benchmark"] is True
    finally:
        get_settings.cache_clear()
