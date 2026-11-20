from __future__ import annotations
from typing import Any, List
from unittest.mock import AsyncMock
import pytest

from src.config import Settings
from src.db.repository import TourRepository
from src.discovery.base_adapter import AgencyFetchError, BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem
from src.schemas.tour_schema import ComparisonFlags, OkinawaTourPackage, PricingDetail
from src.services.pipeline_service import PipelineService


class StubAdapter(BaseAgencyAdapter):
    def __init__(self, key: str, name: str, price: int, should_fail: bool = False):
        super().__init__()
        self.agency_key = key
        self.agency_name = name
        self.price = price
        self.should_fail = should_fail

    async def fetch_tours(self):
        if self.should_fail:
            raise AgencyFetchError(f"[{self.agency_name}] 模擬 API 改版失敗")
        return (
            [
                TourListItem(
                    agency=self.agency_name,
                    tour_code="OKA2027_01",
                    tour_name=f"{self.agency_name} 沖繩春節五日",
                    departure_date="2027-02-04",
                    days=5,
                    departure_airport="TPE",
                    adult_price=self.price,
                    seats_available=16,
                    status="保證出團",
                    detail_url="https://example.com/oka2027",
                    raw_hash=f"hash_{self.price}",
                )
            ],
            "mode_a_xhr",
        )

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        return []

    def parse_xhr_payload(self, payload: Any) -> List[TourListItem]:
        return []


@pytest.mark.asyncio
async def test_pipeline_incremental_caching_and_price_drop_alert(tmp_path):
    db_file = str(tmp_path / "pipeline_test.db")
    settings = Settings(_env_file=None, DATABASE_PATH=db_file, MAX_NEW_DETAILS_PER_RUN=15)
    repo = TourRepository(db_file)

    mock_crawler = AsyncMock()
    mock_crawler.parse_url.return_value = OkinawaTourPackage(
        agency="雄獅旅遊",
        tour_code="OKA2027_01",
        tour_name="雄獅旅遊 沖繩春節五日（無購物站）",
        days=5,
        nights=4,
        departure_date="2027-02-04",
        departure_airport="TPE",
        seats_available=16,
        pricing=PricingDetail(adult_twin_price=48000, tip_per_day_twd=300),
        comparison_flags=ComparisonFlags(has_shopping_station=False, no_hotel_change=True),
    )

    # 第一次執行：新團號 -> 應該呼叫 1 次 DetailCrawler LLM 解析
    adapter_run1 = StubAdapter("lion", "雄獅旅遊", price=48000)
    service1 = PipelineService(
        settings=settings,
        repository=repo,
        detail_crawler=mock_crawler,
        adapters=[adapter_run1],
    )
    res1 = await service1.run_daily_pipeline(skip_flight_benchmark=True)
    assert res1["status"] == "SUCCESS"
    assert res1["stats"]["total_discovered"] == 1
    assert res1["stats"]["llm_calls_used"] == 1
    assert res1["stats"]["llm_skipped_cached"] == 0
    assert mock_crawler.parse_url.await_count == 1
    assert any(a["alert_type"] in {"NEW_HIGH_VALUE_TOUR", "NEW_TOUR"} for a in res1["alerts"])

    # 第二次執行：已存在且未滿 7 天，價格調降 2,000 元 -> 不可重複呼叫 LLM，且應觸發 PRICE_DROP
    adapter_run2 = StubAdapter("lion", "雄獅旅遊", price=46000)
    service2 = PipelineService(
        settings=settings,
        repository=repo,
        detail_crawler=mock_crawler,
        adapters=[adapter_run2],
    )
    res2 = await service2.run_daily_pipeline(skip_flight_benchmark=True)
    assert res2["status"] == "SUCCESS"
    assert res2["stats"]["llm_calls_used"] == 0
    assert res2["stats"]["llm_skipped_cached"] == 1
    assert mock_crawler.parse_url.await_count == 1  # 總次數維持 1 次
    assert any(a["alert_type"] == "PRICE_DROP" for a in res2["alerts"])


@pytest.mark.asyncio
async def test_pipeline_single_agency_failure_isolation(tmp_path):
    db_file = str(tmp_path / "pipeline_isolation.db")
    settings = Settings(_env_file=None, DATABASE_PATH=db_file)
    repo = TourRepository(db_file)

    mock_crawler = AsyncMock()
    mock_crawler.parse_url.return_value = OkinawaTourPackage(
        agency="可樂旅遊",
        tour_code="OKA2027_01",
        tour_name="可樂旅遊 沖繩春節五日",
        days=5,
        nights=4,
        departure_date="2027-02-04",
        departure_airport="TPE",
        seats_available=16,
        pricing=PricingDetail(adult_twin_price=43000, tip_per_day_twd=300),
    )

    failing_lion = StubAdapter("lion", "雄獅旅遊", price=0, should_fail=True)
    healthy_cola = StubAdapter("cola", "可樂旅遊", price=43000, should_fail=False)

    service = PipelineService(
        settings=settings,
        repository=repo,
        detail_crawler=mock_crawler,
        adapters=[failing_lion, healthy_cola],
    )
    res = await service.run_daily_pipeline(skip_flight_benchmark=True)
    assert res["status"] == "PARTIAL_SUCCESS"
    assert len(res["errors"]) == 1
    assert res["stats"]["total_discovered"] == 1
    assert res["stats"]["agencies"]["雄獅旅遊"]["status"] == "ERROR"
    assert res["stats"]["agencies"]["可樂旅遊"]["status"] == "OK"
    assert any(a["alert_type"] == "AGENCY_CRAWL_ERROR" for a in res["alerts"])
