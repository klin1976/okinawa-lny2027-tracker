from __future__ import annotations

from src.calculator.alert_detector import AlertDetector
from src.calculator.budget_engine import BudgetEngine
from src.config import load_trip_config
from src.evaluator import DiffEngine, RuleEvaluator
from src.schemas.budget_schema import CostBreakdown, FamilyBudgetResult
from src.schemas.tour_schema import (
    AttractionItem,
    ComparisonFlags,
    DailyItinerary,
    FlightLeg,
    FlightSummary,
    PricingDetail,
    TourPackage,
)


def _sample_members_profile(child_bed_age_threshold: int) -> dict:
    return {
        "child_bed_age_threshold": child_bed_age_threshold,
        "members": [
            {"role": "adult", "count": 2, "require_bed": True, "require_flight_seat": True},
            {"role": "child", "count": 1, "age": 10, "require_bed": False, "require_flight_seat": True},
            {"role": "child", "count": 1, "age": 8, "require_bed": False, "require_flight_seat": True},
        ],
        "defaults": {
            "tip_per_day_twd": 300,
            "tip_exempt_under_age": 2,
            "fallback_child_no_bed_diff": -5000,
            "fallback_single_room_supplement": 10000,
        },
        "rooming": {"prefer_triple_room_for_odd_pax": True},
    }


def test_child_bed_age_threshold_japan_vs_europe():
    # 日本線：滿 6 歲強制佔床 -> 8 歲與 10 歲皆須佔床 => 共 4 床
    jp_engine = BudgetEngine(_sample_members_profile(child_bed_age_threshold=6))
    jp_demands = jp_engine.calculate_demands()
    assert jp_demands["total_beds_needed"] == 4

    # 歐洲線：門檻設為 12 歲 -> 8 歲與 10 歲可不佔床 => 僅 2 床
    eu_engine = BudgetEngine(_sample_members_profile(child_bed_age_threshold=12))
    eu_demands = eu_engine.calculate_demands()
    assert eu_demands["total_beds_needed"] == 2

    eu_tour = TourPackage(
        trip_id="europe_summer2027",
        agency="雄獅旅遊",
        tour_code="EU12",
        tour_name="奧捷12日",
        days=12,
        nights=10,
        seats_available=10,
        pricing=PricingDetail(adult_twin_price=90000, tip_per_day_twd=450),
    )
    eu_budget = eu_engine.calculate(eu_tour)
    assert eu_budget.breakdown.child_with_bed_total == 0
    assert eu_budget.breakdown.child_no_bed_total == 2 * (90000 - 5000)


def test_rule_evaluator_scoring_tags_and_korea_shopping_stop():
    korea_cfg = load_trip_config("korea_spring2027", trips_dir="config/trips")
    engine = BudgetEngine(korea_cfg)

    clean_tour = TourPackage(
        trip_id="korea_spring2027",
        agency="山富旅遊",
        tour_code="KR_CLEAN",
        tour_name="韓國首爾無購物賞櫻五日",
        days=5,
        nights=4,
        status="保證出團",
        seats_available=20,
        flights=FlightSummary(
            is_direct=True,
            time_band="早去晚回",
            outbound=FlightLeg(airline="中華航空", departure_airport="TPE", arrival_airport="ICN", stops=0),
        ),
        pricing=PricingDetail(adult_twin_price=28000, tip_per_day_twd=300),
        comparison_flags=ComparisonFlags(has_shopping_station=False, no_hotel_change=True),
    )
    budget_clean = engine.calculate(clean_tour)
    eval_clean = RuleEvaluator.evaluate(clean_tour, budget_clean, trip_config=korea_cfg)
    assert eval_clean.is_passed is True
    assert eval_clean.score >= 95.0
    assert "保證出團" in eval_clean.tags
    assert "無購物" in eval_clean.tags
    assert "直飛" in eval_clean.tags
    assert "低於目標預算" in eval_clean.tags
    assert clean_tour.score == eval_clean.score

    # 測試韓國景點關鍵字「人蔘」自動判定含購物站
    shopping_tour = TourPackage(
        trip_id="korea_spring2027",
        agency="世邦旅遊",
        tour_code="KR_SHOP",
        tour_name="韓國首爾超值五日",
        days=5,
        nights=4,
        status="可報名",
        seats_available=20,
        pricing=PricingDetail(adult_twin_price=19900, tip_per_day_twd=300),
        itinerary=[
            DailyItinerary(
                day_number=3,
                day_title="市區觀光",
                attractions=[AttractionItem(name="韓國人蔘專賣店", is_shopping_stop=False)],
            )
        ],
    )
    budget_shop = engine.calculate(shopping_tour)
    eval_shop = RuleEvaluator.evaluate(shopping_tour, budget_shop, trip_config=korea_cfg)
    assert "含購物站" in eval_shop.tags
    assert "含購物站" in eval_shop.failed_rules
    assert eval_shop.score < eval_clean.score


def test_alert_detector_seats_released_and_guaranteed_departure_and_diff_engine():
    detector = AlertDetector({"alerts": {"price_drop_per_adult_twd": 1500, "price_drop_family_total_twd": 10000, "seat_buffer": 4}})
    budget = FamilyBudgetResult(
        tour_uid="雄獅旅遊:KR01:2027-04-02",
        grand_total_twd=300000,
        avg_cost_per_person_twd=30000,
        total_family_members=10,
        total_flight_seats_needed=10,
        total_beds_needed=9,
        seat_status="SUFFICIENT",
        breakdown=CostBreakdown(),
    )

    prev_snap = {"adult_price": 32000, "seats_available": 0, "status": "滿團", "estimated_family_total": 320000}
    curr_snap = {"adult_price": 30000, "seats_available": 12, "status": "保證出團"}

    alerts = detector.detect_alerts(
        tour_uid="雄獅旅遊:KR01:2027-04-02",
        current_snapshot=curr_snap,
        prev_snapshot=prev_snap,
        budget_result=budget,
    )
    types = {a.alert_type for a in alerts}
    assert "PRICE_DROP" in types
    assert "SEATS_RELEASED" in types
    assert "GUARANTEED_DEPARTURE" in types

    report = DiffEngine.build_report(alerts)
    assert len(report.price_drops) == 1
    assert len(report.seats_released) == 1
    assert len(report.guaranteed_departures) == 1
    assert report.total_count == 3
    summary = report.to_summary_dict()
    assert summary["seats_released_count"] == 1
    assert summary["price_drop_count"] == 1
