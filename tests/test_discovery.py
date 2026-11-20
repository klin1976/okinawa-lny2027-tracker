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
    <div class="products-grid">
      <div class="product">
        <div class="cardBox">
          <h6 class="tourCard name">山富桃園出發沖繩美麗海4日</h6>
          <div class="tour-info"><i class="fa-clock"></i><span>4 天</span></div>
          <div class="tour-info"><i class="fa-location-arrow"></i><span>桃園國際機場出發</span></div>
          <div class="price-deposit-h"><span class="price">$27,000</span></div>
          <div class="item inline-block">
            <a href="/group/product/OKA04270202A">
              <h6>02/02</h6>
              <small>保證出團 可售: 0</small>
            </a>
          </div>
          <div class="item inline-block">
            <a href="/group/product/OKA04270205B">
              <h6>02/05</h6>
              <small>可售: 7</small>
            </a>
          </div>
          <div class="item inline-block">
            <a href="/group/product/OKA04270208C">
              <h6>02/08</h6>
              <small>滿團 可售: 0</small>
            </a>
          </div>
        </div>
      </div>
    </div>
    """
    items_r = richmont.parse_dom_fallback(html_r)
    assert len(items_r) == 3
    assert items_r[0].tour_code == "OKA04270202A"
    assert items_r[0].departure_date == "2027-02-02"
    assert items_r[0].days == 4
    assert items_r[0].departure_airport == "TPE"
    assert items_r[0].adult_price == 27000
    assert items_r[0].seats_available == 0
    assert items_r[0].status == "保證出團"
    assert items_r[0].detail_url == "https://www.travel4u.com.tw/group/product/OKA04270202A"
    assert items_r[1].tour_code == "OKA04270205B"
    assert items_r[1].seats_available == 7
    assert items_r[1].status == "可報名"
    assert items_r[2].status == "滿團"

    fourp = FourPAdapter(common_filters=COMMON_FILTERS)
    html_f = """
    <div id="search-block">
      <figure class="block_style">
        <div class="go_number"><h6>OKACI270210GE</h6></div>
        <div class="main_words">
          <a href="/products/group/detail?id=OKACI270210GE&sacct_no=23420481">
            <h4>《沖繩好好玩》HAPPY GO四日～高雄出發</h4>
          </a>
        </div>
        <div class="go-date">2027/02/10(三)</div>
        <div class="item_days">4天</div>
        <div class="go-airport"><span class="airport">高雄小港機場</span></div>
        <div class="price_box"><span class="text-danger">$34,888</span></div>
        <div class="available"><span class="text-danger">15</span></div>
        <div class="go_tag"><a class="tag">保證出發</a><a class="tag d-none">額滿</a></div>
        <a class="btn btn-primary" href="/products/group/detail?id=OKACI270210GE&sacct_no=23420481">報名</a>
      </figure>
    </div>
    """
    items_f = fourp.parse_dom_fallback(html_f)
    assert len(items_f) == 1
    assert items_f[0].tour_code == "OKACI270210GE"
    assert items_f[0].departure_date == "2027-02-10"
    assert items_f[0].days == 4
    assert items_f[0].departure_airport == "KHH"
    assert items_f[0].adult_price == 34888
    assert items_f[0].seats_available == 15
    assert items_f[0].status == "保證出團"
    assert items_f[0].detail_url == "https://www.4p.com.tw/products/group/detail?id=OKACI270210GE&sacct_no=23420481"


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
    assert [a.agency_key for a in adapters] == ["lion", "richmont", "fourp"]


def test_cola_waf_block_raises_runtime_error():
    cola = ColaAdapter(common_filters=COMMON_FILTERS)
    with pytest.raises(RuntimeError, match="WAF"):
        cola._check_waf_block(435, "<html>網站連線異常</html>")
