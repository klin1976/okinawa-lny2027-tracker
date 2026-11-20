from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.db.database import init_db
from src.db.repository import TourRepository
from src.extractor.detail_crawler import DetailExtractionError
from src.main import app
from src.schemas.discovery_schema import TourListItem
from src.schemas.tour_schema import ComparisonFlags, OkinawaTourPackage, PricingDetail


TEST_API_KEY = "test-secret-key-2027"


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    db_file = tmp_path / "api_test.db"
    monkeypatch.setenv("API_KEY", TEST_API_KEY)
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    get_settings.cache_clear()

    with TestClient(app) as client:
        yield client, str(db_file)

    get_settings.cache_clear()


def _headers(key: str = TEST_API_KEY) -> Dict[str, str]:
    return {"X-API-Key": key}


def test_health_unauthenticated(api_client):
    client, _ = api_client
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db_connected"] is True
    assert body["last_run_at"] is None


def test_api_key_auth_rejects_missing_and_wrong_key(api_client):
    client, _ = api_client
    protected_calls = [
        ("POST", "/api/v1/pipeline/daily-run", {}),
        ("POST", "/api/v1/extract/single", {"url": "https://example.com/tour"}),
        ("GET", "/api/v1/rankings", None),
        ("GET", "/api/v1/tours/nonexistent/history", None),
    ]
    for method, path, payload in protected_calls:
        resp_missing = client.request(method, path, json=payload)
        assert resp_missing.status_code == 401

        resp_wrong = client.request(method, path, json=payload, headers=_headers("wrong-key"))
        assert resp_wrong.status_code == 401


def test_pipeline_daily_run_mocked(api_client, monkeypatch):
    client, _ = api_client
    captured: Dict[str, Any] = {}

    async def fake_run_daily_pipeline(
        self,
        agencies=None,
        force_reparse=False,
        max_new_details_per_run=None,
        skip_flight_benchmark=False,
    ):
        captured["agencies"] = agencies
        captured["force_reparse"] = force_reparse
        captured["max_new_details_per_run"] = max_new_details_per_run
        captured["skip_flight_benchmark"] = skip_flight_benchmark
        return {
            "run_at": "2026-11-20T09:00:00+08:00",
            "tours_discovered": 12,
            "alerts": [],
            "top_5_rankings": [],
        }

    monkeypatch.setattr(
        "src.services.pipeline_service.PipelineService.run_daily_pipeline",
        fake_run_daily_pipeline,
    )

    resp = client.post(
        "/api/v1/pipeline/daily-run",
        json={
            "agencies": ["richmont", "fourp"],
            "force_reparse": True,
            "max_new_details_per_run": 5,
            "skip_flight_benchmark": True,
        },
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["tours_discovered"] == 12
    assert captured == {
        "agencies": ["richmont", "fourp"],
        "force_reparse": True,
        "max_new_details_per_run": 5,
        "skip_flight_benchmark": True,
    }


def test_extract_single_mocked_and_error(api_client, monkeypatch):
    client, _ = api_client

    sample_pkg = OkinawaTourPackage(
        agency="山富旅遊",
        tour_code="OKA04270202A",
        tour_name="山富沖繩美麗海四日",
        source_url="https://www.travel4u.com.tw/group/product/OKA04270202A",
        days=4,
        nights=3,
        departure_date="2027-02-02",
        departure_airport="TPE",
        seats_available=16,
        status="保證出團",
        pricing=PricingDetail(adult_twin_price=35000, tip_total_per_person=1200),
        comparison_flags=ComparisonFlags(has_shopping_station=False),
    )

    async def fake_parse_url(self, url: str, agency_hint=None):
        assert url == "https://www.travel4u.com.tw/group/product/OKA04270202A"
        assert agency_hint == "山富旅遊"
        return sample_pkg

    monkeypatch.setattr("src.extractor.detail_crawler.DetailCrawler.parse_url", fake_parse_url)

    resp = client.post(
        "/api/v1/extract/single",
        json={
            "url": "https://www.travel4u.com.tw/group/product/OKA04270202A",
            "agency_hint": "山富旅遊",
        },
        headers=_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tour"]["tour_code"] == "OKA04270202A"
    assert body["budget"]["grand_total_twd"] > 0
    assert body["budget"]["seat_status"] == "SUFFICIENT"

    async def fake_parse_url_fail(self, url: str, agency_hint=None):
        raise DetailExtractionError("Crawl failed")

    monkeypatch.setattr("src.extractor.detail_crawler.DetailCrawler.parse_url", fake_parse_url_fail)
    resp_err = client.post(
        "/api/v1/extract/single",
        json={"url": "https://example.com/bad"},
        headers=_headers(),
    )
    assert resp_err.status_code == 502


def _seed_sample_tours(db_path: str) -> str:
    async def _seed():
        await init_db(db_path)
        repo = TourRepository(db_path)

        tours = [
            (
                TourListItem(
                    agency="山富旅遊",
                    tour_code="TPE_GOOD",
                    tour_name="桃園出發沖繩無購物四日",
                    departure_date="2027-02-02",
                    days=4,
                    departure_airport="TPE",
                    adult_price=32000,
                    seats_available=16,
                    status="保證出團",
                    detail_url="https://example.com/tpe_good",
                ),
                OkinawaTourPackage(
                    agency="山富旅遊",
                    tour_code="TPE_GOOD",
                    tour_name="桃園出發沖繩無購物四日",
                    source_url="https://example.com/tpe_good",
                    days=4,
                    nights=3,
                    departure_date="2027-02-02",
                    departure_airport="TPE",
                    seats_available=16,
                    status="保證出團",
                    pricing=PricingDetail(adult_twin_price=32000, tip_total_per_person=1200),
                    comparison_flags=ComparisonFlags(has_shopping_station=False, includes_churaumi_aquarium=True),
                ),
            ),
            (
                TourListItem(
                    agency="世邦旅遊",
                    tour_code="KHH_SHOP",
                    tour_name="高雄出發沖繩購物站五日",
                    departure_date="2027-02-04",
                    days=5,
                    departure_airport="KHH",
                    adult_price=48000,
                    seats_available=15,
                    status="可報名",
                    detail_url="https://example.com/khh_shop",
                ),
                OkinawaTourPackage(
                    agency="世邦旅遊",
                    tour_code="KHH_SHOP",
                    tour_name="高雄出發沖繩購物站五日",
                    source_url="https://example.com/khh_shop",
                    days=5,
                    nights=4,
                    departure_date="2027-02-04",
                    departure_airport="KHH",
                    seats_available=15,
                    status="可報名",
                    pricing=PricingDetail(adult_twin_price=48000, tip_total_per_person=1500),
                    comparison_flags=ComparisonFlags(has_shopping_station=True),
                ),
            ),
            (
                TourListItem(
                    agency="雄獅旅遊",
                    tour_code="TPE_LOWSEATS",
                    tour_name="桃園出發沖繩低機位四日",
                    departure_date="2027-02-06",
                    days=4,
                    departure_airport="TPE",
                    adult_price=38000,
                    seats_available=4,
                    status="可報名",
                    detail_url="https://example.com/tpe_low",
                ),
                OkinawaTourPackage(
                    agency="雄獅旅遊",
                    tour_code="TPE_LOWSEATS",
                    tour_name="桃園出發沖繩低機位四日",
                    source_url="https://example.com/tpe_low",
                    days=4,
                    nights=3,
                    departure_date="2027-02-06",
                    departure_airport="TPE",
                    seats_available=4,
                    status="可報名",
                    pricing=PricingDetail(adult_twin_price=38000, tip_total_per_person=1200),
                    comparison_flags=ComparisonFlags(has_shopping_station=False),
                ),
            ),
        ]

        first_uid = ""
        for idx, (item, pkg) in enumerate(tours):
            uid = await repo.upsert_tour_from_list(item)
            if idx == 0:
                first_uid = uid
            await repo.update_tour_detail(uid, pkg.model_dump_json())
            await repo.insert_price_snapshot(
                tour_uid=uid,
                adult_price=item.adult_price,
                seats_available=item.seats_available,
                status=item.status,
                estimated_family_total=None,
            )
        return first_uid

    return asyncio.run(_seed())


def test_rankings_filtering_and_sorting(api_client):
    client, db_path = api_client
    _seed_sample_tours(db_path)

    resp_all = client.get("/api/v1/rankings", headers=_headers())
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert data_all["total"] == 3
    scores = [r["composite_score"] for r in data_all["rankings"]]
    assert scores == sorted(scores, reverse=True)

    resp_tpe = client.get("/api/v1/rankings?airport=TPE", headers=_headers())
    assert resp_tpe.status_code == 200
    assert resp_tpe.json()["total"] == 2
    assert all(r["departure_airport"] == "TPE" for r in resp_tpe.json()["rankings"])

    resp_noshop = client.get("/api/v1/rankings?no_shopping=true", headers=_headers())
    assert resp_noshop.status_code == 200
    assert resp_noshop.json()["total"] == 2

    resp_seats = client.get("/api/v1/rankings?only_enough_seats=true", headers=_headers())
    assert resp_seats.status_code == 200
    assert resp_seats.json()["total"] == 2
    assert all(r["budget"]["seat_status"] == "SUFFICIENT" for r in resp_seats.json()["rankings"])

    resp_limit = client.get("/api/v1/rankings?limit=1", headers=_headers())
    assert resp_limit.status_code == 200
    assert resp_limit.json()["total"] == 3
    assert len(resp_limit.json()["rankings"]) == 1


def test_tour_history_404_and_200(api_client):
    client, db_path = api_client
    first_uid = _seed_sample_tours(db_path)

    resp_404 = client.get("/api/v1/tours/unknown:123:2027-02-01/history", headers=_headers())
    assert resp_404.status_code == 404

    resp_200 = client.get(f"/api/v1/tours/{first_uid}/history", headers=_headers())
    assert resp_200.status_code == 200
    body = resp_200.json()
    assert body["tour_uid"] == first_uid
    assert body["agency"] == "山富旅遊"
    assert len(body["price_snapshots"]) == 1
    assert body["price_snapshots"][0]["adult_price"] == 32000
