from __future__ import annotations
from typing import Any, List
import pytest

from src.config import load_agencies_config
from src.discovery import (
    BaseAgencyAdapter,
    ColaAdapter,
    FourPAdapter,
    LionAdapter,
    RichmontAdapter,
    SettourAdapter,
    build_enabled_adapters,
)
from src.discovery.base_adapter import AgencyFetchError
from src.schemas.discovery_schema import TourListItem


COMMON_FILTERS = {
    "destination_keywords": ["沖繩", "琉球", "OKA"],
    "departure_date_range": {"start": "2027-02-01", "end": "2027-02-14"},
    "max_days": 5,
}


def test_five_agencies_xhr_parsing_and_filtering():
    lion = LionAdapter(common_filters=COMMON_FILTERS)
    lion_items = lion.parse_xhr_payload(
        {
            "NormGroupList": [
                {
                    "NormGroupID": "27JN204BR",
                    "TourName": "春節沖繩美麗海五日",
                    "GoDate": "2027/02/04",
                    "TourDays": 5,
                    "GroupStraightPrice": "46900",
                    "AvailableVacancy": 14,
                    "IsGuaranteed": True,
                    "DepartureCity": "桃園",
                },
                {
                    "NormGroupID": "27JN999BR",
                    "TourName": "沖繩六日遊(應被天數過濾)",
                    "GoDate": "2027/02/04",
                    "TourDays": 6,
                    "GroupStraightPrice": 52000,
                    "AvailableVacancy": 10,
                },
            ]
        }
    )
    assert len(lion_items) == 1
    assert lion_items[0].agency == "雄獅旅遊"
    assert lion_items[0].departure_airport == "TPE"
    assert lion_items[0].status == "保證出團"
    assert lion_items[0].adult_price == 46900

    cola = ColaAdapter(common_filters=COMMON_FILTERS)
    cola_items = cola.parse_xhr_payload(
        {
            "TourList": [
                {
                    "PatternNo": "NKD020604CI7",
                    "PatternName": "高雄出發沖繩四日",
                    "BeginDate": "2027-02-06",
                    "TourDays": 4,
                    "Price": 39900,
                    "RemainSeats": 12,
                    "DepartCity": "KHH",
                }
            ]
        }
    )
    assert len(cola_items) == 1
    assert cola_items[0].departure_airport == "KHH"
    assert "TourCode=NKD020604CI7" in cola_items[0].detail_url

    settour = SettourAdapter(common_filters=COMMON_FILTERS)
    settour_items = settour.parse_xhr_payload(
        {
            "prodList": [
                {
                    "prodNo": "GFG0000123",
                    "prodNm": "東南賀歲琉球五日",
                    "begDt": "20270205",
                    "prodDays": 5,
                    "b2cAmt": 44500,
                    "availQty": 16,
                    "departAirport": "TPE",
                }
            ]
        }
    )
    assert len(settour_items) == 1
    assert settour_items[0].departure_date == "2027-02-05"
    assert settour_items[0].seats_available == 16

    richmont = RichmontAdapter(common_filters=COMMON_FILTERS)
    richmont_items = richmont.parse_xhr_payload(
        {
            "tours": [
                {
                    "tourCode": "OKA270204",
                    "tourName": "山富沖繩親子五日",
                    "departDate": "2027-02-04",
                    "days": 5,
                    "price": 42800,
                    "seats": 8,
                }
            ]
        }
    )
    assert len(richmont_items) == 1
    assert richmont_items[0].agency == "山富旅遊"

    fourp = FourPAdapter(common_filters=COMMON_FILTERS)
    fourp_items = fourp.parse_xhr_payload(
        {
            "tours": [
                {
                    "tourCode": "4P270207",
                    "tourName": "世邦OKAC春節四日",
                    "departDate": "2027-02-07",
                    "days": 4,
                    "price": 38800,
                    "seats": 20,
                }
            ]
        }
    )
    assert len(fourp_items) == 1
    assert fourp_items[0].agency == "世邦旅遊"


def test_dom_fallback_for_richmont_and_fourp():
    richmont = RichmontAdapter(common_filters=COMMON_FILTERS)
    html_r = """
    <div class="tour-card" data-tour-code="RM270205" data-depart-date="2027-02-05">
        <a href="/group/itinerary/RM270205"><h3>山富桃園出發沖繩5日</h3></a>
        <span class="price">NT$41,900</span>
        <span class="seats">12席</span>
    </div>
    """
    items_r = richmont.parse_dom_fallback(html_r)
    assert len(items_r) == 1
    assert items_r[0].tour_code == "RM270205"
    assert items_r[0].adult_price == 41900
    assert items_r[0].seats_available == 12

    fourp = FourPAdapter(common_filters=COMMON_FILTERS)
    html_f = """
    <div class="tour-item" data-code="FP270208" data-date="2027-02-08">
        <a href="/tour/FP270208"><h3>世邦高雄沖繩4日</h3></a>
        <span class="price">36900</span>
        <span class="qty">10</span>
    </div>
    """
    items_f = fourp.parse_dom_fallback(html_f)
    assert len(items_f) == 1
    assert items_f[0].tour_code == "FP270208"
    assert items_f[0].departure_airport == "KHH"


class MockFallbackAdapter(BaseAgencyAdapter):
    agency_key = "lion"
    agency_name = "雄獅旅遊"

    def __init__(self, fail_mode_a: bool = True, fail_mode_b: bool = False):
        super().__init__(common_filters=COMMON_FILTERS)
        self.fail_mode_a = fail_mode_a
        self.fail_mode_b = fail_mode_b

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        if self.fail_mode_a:
            raise RuntimeError("HTTP 403 WAF Blocked")
        return self._sample_items()

    async def fetch_mode_b_playwright(self) -> List[TourListItem]:
        if self.fail_mode_b:
            raise RuntimeError("Playwright Timeout")
        return self._sample_items()

    def parse_xhr_payload(self, payload: Any) -> List[TourListItem]:
        return []

    def _sample_items(self) -> List[TourListItem]:
        return [
            TourListItem(
                agency="雄獅旅遊",
                tour_code="OKA_OK",
                tour_name="沖繩五日春節團",
                departure_date="2027-02-04",
                days=5,
                departure_airport="TPE",
                adult_price=45000,
                seats_available=15,
                status="可報名",
                detail_url="https://example.com/ok",
            ),
            # 應該被過濾器排除（非春節區間）
            TourListItem(
                agency="雄獅旅遊",
                tour_code="OKA_LATE",
                tour_name="沖繩五日三月團",
                departure_date="2027-03-01",
                days=5,
                departure_airport="TPE",
                adult_price=25000,
                seats_available=15,
                status="可報名",
                detail_url="https://example.com/late",
            ),
            # 應該被過濾器排除（非沖繩）
            TourListItem(
                agency="雄獅旅遊",
                tour_code="TOKYO_1",
                tour_name="東京五日春節團",
                departure_date="2027-02-04",
                days=5,
                departure_airport="TPE",
                adult_price=55000,
                seats_available=15,
                status="可報名",
                detail_url="https://example.com/tokyo",
            ),
        ]


@pytest.mark.asyncio
async def test_dual_mode_fallback_and_both_fail():
    adapter = MockFallbackAdapter(fail_mode_a=True, fail_mode_b=False)
    items, mode = await adapter.fetch_tours()
    assert mode == "mode_b_playwright"
    assert len(items) == 1
    assert items[0].tour_code == "OKA_OK"

    broken = MockFallbackAdapter(fail_mode_a=True, fail_mode_b=True)
    with pytest.raises(AgencyFetchError):
        await broken.fetch_tours()


def test_build_enabled_adapters_from_yaml():
    cfg = load_agencies_config("config/agencies.yaml")
    adapters = build_enabled_adapters(cfg)
    assert len(adapters) == 5
