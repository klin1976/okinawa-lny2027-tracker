from __future__ import annotations

from typing import Any, List

from src.config import list_trip_configs, load_family_profile, load_trip_config
from src.discovery.base_adapter import BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem
from src.schemas.tour_schema import DailyItinerary, HotelStay, TourPackage


class DummyTripAdapter(BaseAgencyAdapter):
    agency_key = "lion"
    agency_name = "雄獅旅遊"

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        return []

    def parse_xhr_payload(self, payload: Any) -> List[TourListItem]:
        return []


def test_load_all_four_multi_destination_trips():
    all_trips = list_trip_configs("config/trips", enabled_only=False)
    trip_ids = {t.trip_id for t in all_trips}
    assert {
        "okinawa_lny2027",
        "hokkaido_winter2027",
        "korea_spring2027",
        "europe_summer2027",
    }.issubset(trip_ids)

    enabled_trips = list_trip_configs("config/trips", enabled_only=True)
    assert [t.trip_id for t in enabled_trips] == ["okinawa_lny2027"]


def test_europe_trip_config_overrides_and_inheritance():
    europe = load_trip_config("europe_summer2027", trips_dir="config/trips")
    assert europe.destination.country == "歐洲"
    assert europe.schedule.min_days == 9
    assert europe.schedule.max_days == 13
    assert europe.flight_benchmark.max_stops == 1
    assert europe.party.child_bed_age_threshold == 12
    assert europe.party.tip_per_day_twd == 450

    base_profile = load_family_profile("config/family_profile.yaml")
    effective = europe.build_effective_profile(base_profile)
    assert effective["child_bed_age_threshold"] == 12
    assert effective["defaults"]["tip_per_day_twd"] == 450
    assert effective["target_total_budget_twd"] == 950000
    assert len(effective["members"]) == len(base_profile["members"])


def test_adapter_common_filters_for_europe_and_exclude_keywords():
    europe = load_trip_config("europe_summer2027", trips_dir="config/trips")
    adapter = DummyTripAdapter(trip_config=europe)
    assert adapter.get_min_days() == 9
    assert adapter.get_max_days() == 13

    items = [
        TourListItem(
            agency="雄獅旅遊",
            tour_code="EU_OK_12",
            tour_name="奧捷經典夢幻12日",
            departure_date="2027-07-15",
            days=12,
            departure_airport="TPE",
            adult_price=89900,
            seats_available=15,
            status="保證出團",
            detail_url="https://example.com/eu12",
        ),
        TourListItem(
            agency="雄獅旅遊",
            tour_code="EU_CRUISE",
            tour_name="歐洲多瑙河郵輪12日",
            departure_date="2027-07-15",
            days=12,
            departure_airport="TPE",
            adult_price=120000,
            seats_available=15,
            status="可報名",
            detail_url="https://example.com/cruise",
        ),
        TourListItem(
            agency="雄獅旅遊",
            tour_code="EU_SHORT",
            tour_name="奧捷快閃6日",
            departure_date="2027-07-15",
            days=6,
            departure_airport="TPE",
            adult_price=60000,
            seats_available=15,
            status="可報名",
            detail_url="https://example.com/short",
        ),
    ]

    filtered = adapter.apply_common_filters(items)
    assert len(filtered) == 1
    assert filtered[0].tour_code == "EU_OK_12"
    assert filtered[0].trip_id == "europe_summer2027"


def test_tour_package_supports_long_haul_days_and_free_regions():
    pkg = TourPackage(
        trip_id="europe_summer2027",
        destination_country="歐洲",
        destination_region="奧捷/德瑞",
        agency="雄獅旅遊",
        tour_code="EU_12D",
        tour_name="奧捷12日深度遊",
        days=12,
        nights=10,
        itinerary=[
            DailyItinerary(
                day_number=10,
                day_title="布拉格舊城巡禮",
                hotel=HotelStay(candidate_hotels=["布拉格五星飯店"], area="布拉格市中心"),
            )
        ],
    )
    assert pkg.days == 12
    assert pkg.itinerary[0].day_number == 10
    assert pkg.itinerary[0].hotel.area == "布拉格市中心"
