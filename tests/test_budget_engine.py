import pytest
from src.calculator.budget_engine import BudgetEngine
from src.schemas.tour_schema import (
    ComparisonFlags,
    DailyItinerary,
    FlightLeg,
    FlightSummary,
    OkinawaTourPackage,
    PricingDetail,
    ChildPricing,
    SeniorAndSpecialPolicy,
)


@pytest.fixture
def sample_family_profile():
    return {
        "family_name": "測試家族團",
        "members": [
            {"role": "adult", "count": 6, "require_bed": True, "require_flight_seat": True},
            {"role": "senior", "count": 1, "age": 70, "require_bed": True, "require_flight_seat": True},
            {"role": "child", "count": 1, "age": 10, "require_bed": True, "require_flight_seat": True},
            # 測試：宣告不佔床，但滿 6 歲（8歲）必須被日本法規強制佔床
            {"role": "child", "count": 1, "age": 8, "require_bed": False, "require_flight_seat": True},
            # 測試：未滿 6 歲（2歲）不佔床
            {"role": "child", "count": 1, "age": 2, "require_bed": False, "require_flight_seat": True},
            # 測試：未滿 2 歲嬰兒，免機位免佔床免小費
            {"role": "infant", "count": 1, "age": 1, "require_bed": False, "require_flight_seat": False},
        ],
        "defaults": {
            "tip_per_day_twd": 300,
            "tip_exempt_under_age": 2,
            "fallback_child_no_bed_diff": -3000,
            "fallback_infant_price": 6000,
            "fallback_single_room_supplement": 12000,
        },
        "rooming": {
            "prefer_triple_room_for_odd_pax": True,
        },
        "scoring_weights": {
            "avoid_shopping_stop_bonus": 15,
            "no_hotel_change_bonus": 10,
            "early_out_late_back_bonus": 12,
            "kid_friendly_attraction_bonus": 8,
            "senior_restriction_penalty": -5,
            "too_many_self_paid_meals_penalty": -5,
        },
    }


def test_demands_and_japanese_6yo_bed_rule(sample_family_profile):
    engine = BudgetEngine(sample_family_profile)
    demands = engine.calculate_demands()

    # 總人數: 6 adult + 1 senior + 3 child + 1 infant = 11 pax
    assert demands["total_pax"] == 11

    # 機位需求: 6 adult + 1 senior + 3 child = 10 seats (infant 不需要)
    assert demands["total_flight_seats_needed"] == 10

    # 床位需求:
    # 6 adult + 1 senior + 1 child(10yo) + 1 child(8yo, 強制佔床) = 9 beds
    # 2yo 與 infant 不佔床
    assert demands["total_beds_needed"] == 9


def test_odd_beds_triple_room_allowed(sample_family_profile):
    engine = BudgetEngine(sample_family_profile)
    tour = OkinawaTourPackage(
        agency="雄獅旅遊",
        tour_code="27JN01",
        tour_name="沖繩春節五日(允許加床三人房)",
        days=5,
        nights=4,
        pricing=PricingDetail(
            adult_twin_price=45000,
            single_room_supplement=12000,
            triple_room_policy="可配合提供加床服務/三人房",
        ),
    )
    result = engine.calculate(tour)

    # 9 床為奇數，但允許三人房且 prefer_triple_room_for_odd_pax=True，故單人房差為 0
    assert result.breakdown.single_supplement_total == 0
    assert any("免收單人房差" in a for a in result.assumptions)


def test_odd_beds_no_triple_room_adds_single_supplement(sample_family_profile):
    engine = BudgetEngine(sample_family_profile)
    tour = OkinawaTourPackage(
        agency="可樂旅遊",
        tour_code="27COL01",
        tour_name="沖繩春節五日(無法加床)",
        days=5,
        nights=4,
        pricing=PricingDetail(
            adult_twin_price=46000,
            single_room_supplement=15000,
            triple_room_policy="本飯店無法加床、無三人房",
        ),
    )
    result = engine.calculate(tour)

    # 9 床為奇數且明確標明無法加床 -> 加計單人房差 15000
    assert result.breakdown.single_supplement_total == 15000
    assert any("加計單人房差" in a for a in result.assumptions)


def test_senior_warning_and_adjustments(sample_family_profile):
    engine = BudgetEngine(sample_family_profile)
    tour = OkinawaTourPackage(
        agency="東南旅遊",
        tour_code="27SET01",
        tour_name="沖繩春節樂遊",
        days=5,
        nights=4,
        pricing=PricingDetail(
            adult_twin_price=42000,
            senior_policy=SeniorAndSpecialPolicy(
                senior_price_adjustment=-1500,
                senior_age_threshold=70,
                senior_companion_rule="滿70歲高齡旅客須有年滿20歲親友陪同",
                senior_insurance_note="高齡保額上限依保險法規調整",
            ),
        ),
    )
    result = engine.calculate(tour)

    # 長輩折價 1500
    assert result.breakdown.senior_total == (42000 - 1500)
    # 檢查警告訊息
    assert any("滿70歲高齡旅客須有年滿20歲親友陪同" in w for w in result.risk_warnings)
    assert any("高齡保額上限依保險法規調整" in w for w in result.risk_warnings)


def test_seats_sufficient_vs_insufficient(sample_family_profile):
    engine = BudgetEngine(sample_family_profile)

    # 需要 10 席
    tour_sufficient = OkinawaTourPackage(
        agency="山富旅遊",
        tour_code="27RIC01",
        tour_name="山富沖繩充足位",
        days=5,
        nights=4,
        seats_available=12,
        pricing=PricingDetail(adult_twin_price=40000),
    )
    res_suf = engine.calculate(tour_sufficient)
    assert res_suf.seat_status == "SUFFICIENT"
    assert not any("不足家族所需" in w for w in res_suf.risk_warnings)

    tour_insufficient = OkinawaTourPackage(
        agency="世邦旅遊",
        tour_code="274P01",
        tour_name="世邦沖繩不足位",
        days=5,
        nights=4,
        seats_available=6,
        pricing=PricingDetail(adult_twin_price=40000),
    )
    res_insuf = engine.calculate(tour_insufficient)
    assert res_insuf.seat_status == "INSUFFICIENT"
    assert any("不足家族所需" in w for w in res_insuf.risk_warnings)
    # 分數應遭重扣
    assert res_insuf.composite_score < res_suf.composite_score


def test_service_tips_calculation(sample_family_profile):
    engine = BudgetEngine(sample_family_profile)
    tour = OkinawaTourPackage(
        agency="雄獅旅遊",
        tour_code="27JN02",
        tour_name="雄獅沖繩小費測試",
        days=5,
        nights=4,
        pricing=PricingDetail(
            adult_twin_price=40000,
            tip_per_day_twd=300,
        ),
    )
    result = engine.calculate(tour)
    # 11 位中只有 1 位未滿 2 歲嬰兒免小費，其餘 10 位須付小費
    # 300 * 5 天 * 10 人 = 15000
    assert result.breakdown.tips_total == 15000


def test_ranking_three_mock_tours(sample_family_profile):
    engine = BudgetEngine(sample_family_profile)

    tour1 = OkinawaTourPackage(
        agency="雄獅旅遊",
        tour_code="LION-01",
        tour_name="【保證無購物】沖繩蔚藍海景五日",
        days=5,
        nights=4,
        seats_available=15,
        flights=FlightSummary(
            time_band="早去晚回",
            outbound=FlightLeg(
                airline="長榮航空",
                departure_airport="TPE",
                arrival_airport="OKA",
            ),
        ),
        pricing=PricingDetail(adult_twin_price=48000),
        comparison_flags=ComparisonFlags(
            has_shopping_station=False,
            no_hotel_change=True,
            kid_friendly_tags=["美麗海水族館", "星野"],
        ),
    )

    tour2 = OkinawaTourPackage(
        agency="可樂旅遊",
        tour_code="COLA-01",
        tour_name="【超低價特惠】沖繩市區採購五日",
        days=5,
        nights=4,
        seats_available=8,  # 機位不足 (需10位)
        flights=FlightSummary(time_band="晚去早回"),
        pricing=PricingDetail(adult_twin_price=36000),
        comparison_flags=ComparisonFlags(
            has_shopping_station=True,
            total_self_paid_meals=5,
        ),
    )

    tour3 = OkinawaTourPackage(
        agency="東南旅遊",
        tour_code="SET-01",
        tour_name="【經典沖繩】水族館溫泉五日",
        days=5,
        nights=4,
        seats_available=10,
        flights=FlightSummary(time_band="早去午回"),
        pricing=PricingDetail(adult_twin_price=43000),
        comparison_flags=ComparisonFlags(
            has_shopping_station=False,
            kid_friendly_tags=["玉泉洞"],
        ),
    )

    results = [engine.calculate(t) for t in [tour1, tour2, tour3]]

    # 排序測試：評分最高者應為 tour1 (無購物、早去晚回、連住飯店、機位充裕)
    results_by_score = sorted(results, key=lambda r: r.composite_score, reverse=True)
    assert results_by_score[0].tour_uid == "雄獅旅遊:LION-01:NODATE"
    assert results_by_score[-1].tour_uid == "可樂旅遊:COLA-01:NODATE"
    assert results_by_score[-1].seat_status == "INSUFFICIENT"
