import pytest
from src.calculator.alert_detector import AlertDetector
from src.schemas.budget_schema import CostBreakdown, FamilyBudgetResult
from src.schemas.tour_schema import ComparisonFlags, OkinawaTourPackage, PricingDetail


@pytest.fixture
def detector():
    profile = {
        "alerts": {
            "price_drop_per_adult_twd": 1500,
            "price_drop_family_total_twd": 10000,
            "seat_buffer": 4,
        }
    }
    return AlertDetector(profile)


def create_mock_budget_result(grand_total: int, seats_needed: int = 10) -> FamilyBudgetResult:
    return FamilyBudgetResult(
        tour_uid="雄獅旅遊:27JN204BR:2027-02-04",
        grand_total_twd=grand_total,
        avg_cost_per_person_twd=round(grand_total / 10),
        total_family_members=10,
        total_flight_seats_needed=seats_needed,
        total_beds_needed=9,
        seat_status="SUFFICIENT",
        breakdown=CostBreakdown(),
        is_estimated=False,
    )


def test_price_drop_adult_alert(detector):
    prev_snapshot = {
        "adult_price": 45000,
        "seats_available": 15,
        "estimated_family_total": 450000,
    }
    current_snapshot = {
        "adult_price": 43000,  # 降價 2,000 >= 1,500
        "seats_available": 15,
    }
    budget_result = create_mock_budget_result(432000)

    alerts = detector.detect_alerts(
        tour_uid="雄獅旅遊:27JN204BR:2027-02-04",
        current_snapshot=current_snapshot,
        prev_snapshot=prev_snapshot,
        budget_result=budget_result,
    )

    assert len(alerts) == 1
    assert alerts[0].alert_type == "PRICE_DROP"
    assert alerts[0].priority == "高"
    assert "43,000" in alerts[0].message
    assert "2,000" in alerts[0].message


def test_price_drop_family_total_alert(detector):
    prev_snapshot = {
        "adult_price": 45000,
        "seats_available": 15,
        "estimated_family_total": 450000,
    }
    # 單人降 1000 (< 1500)，但總預算降 15000 (>= 10000)
    current_snapshot = {
        "adult_price": 44000,
        "seats_available": 15,
    }
    budget_result = create_mock_budget_result(435000)

    alerts = detector.detect_alerts(
        tour_uid="雄獅旅遊:27JN204BR:2027-02-04",
        current_snapshot=current_snapshot,
        prev_snapshot=prev_snapshot,
        budget_result=budget_result,
    )

    assert len(alerts) == 1
    assert alerts[0].alert_type == "PRICE_DROP"


def test_low_seats_alert(detector):
    # 需 10 席，buffer = 4 -> 門檻 14
    prev_snapshot = {
        "adult_price": 45000,
        "seats_available": 20,
        "estimated_family_total": 450000,
    }
    current_snapshot = {
        "adult_price": 45000,
        "seats_available": 12,  # 12 <= 14 且 >= 10
    }
    budget_result = create_mock_budget_result(450000, seats_needed=10)

    alerts = detector.detect_alerts(
        tour_uid="雄獅旅遊:27JN204BR:2027-02-04",
        current_snapshot=current_snapshot,
        prev_snapshot=prev_snapshot,
        budget_result=budget_result,
    )

    assert len(alerts) == 1
    assert alerts[0].alert_type == "LOW_SEATS"
    assert alerts[0].priority == "中高"
    assert "12" in alerts[0].message


def test_seat_critical_alert(detector):
    prev_snapshot = {
        "adult_price": 45000,
        "seats_available": 12,
        "estimated_family_total": 450000,
    }
    current_snapshot = {
        "adult_price": 45000,
        "seats_available": 6,  # 跌破 10 席
    }
    budget_result = create_mock_budget_result(450000, seats_needed=10)

    alerts = detector.detect_alerts(
        tour_uid="雄獅旅遊:27JN204BR:2027-02-04",
        current_snapshot=current_snapshot,
        prev_snapshot=prev_snapshot,
        budget_result=budget_result,
    )

    assert len(alerts) == 1
    assert alerts[0].alert_type == "SEAT_CRITICAL"
    assert alerts[0].priority == "高"
    assert "不足全家族報名所需" in alerts[0].message


def test_new_high_value_tour_vs_new_tour(detector):
    current_snapshot = {
        "adult_price": 46000,
        "seats_available": 15,
    }
    budget_result = create_mock_budget_result(460000, seats_needed=10)

    tour_high_value = OkinawaTourPackage(
        agency="雄獅旅遊",
        tour_code="27HV01",
        tour_name="超值無購物沖繩",
        days=5,
        nights=4,
        comparison_flags=ComparisonFlags(has_shopping_station=False),
    )

    # 1. 超值新團
    alerts_hv = detector.detect_alerts(
        tour_uid="雄獅旅遊:27HV01:2027-02-04",
        current_snapshot=current_snapshot,
        prev_snapshot=None,
        budget_result=budget_result,
        tour_package=tour_high_value,
        is_top_ranked=True,
    )
    assert len(alerts_hv) == 1
    assert alerts_hv[0].alert_type == "NEW_HIGH_VALUE_TOUR"

    # 2. 一般新團 (有購物站)
    tour_normal = OkinawaTourPackage(
        agency="雄獅旅遊",
        tour_code="27NM01",
        tour_name="一般沖繩團",
        days=5,
        nights=4,
        comparison_flags=ComparisonFlags(has_shopping_station=True),
    )
    alerts_nm = detector.detect_alerts(
        tour_uid="雄獅旅遊:27NM01:2027-02-04",
        current_snapshot=current_snapshot,
        prev_snapshot=None,
        budget_result=budget_result,
        tour_package=tour_normal,
        is_top_ranked=True,
    )
    assert len(alerts_nm) == 1
    assert alerts_nm[0].alert_type == "NEW_TOUR"


def test_alert_deduplication(detector):
    prev_snapshot = {
        "adult_price": 45000,
        "seats_available": 15,
        "estimated_family_total": 450000,
    }
    current_snapshot = {
        "adult_price": 43000,
        "seats_available": 15,
    }
    budget_result = create_mock_budget_result(430000)

    tour_uid = "雄獅旅遊:27JN204BR:2027-02-04"
    alert_key = f"PRICE_DROP:{tour_uid}:43000_430000"

    # 若 alert_key 已經在已發送清單中，則不應重複產出
    existing_keys = {alert_key}

    alerts = detector.detect_alerts(
        tour_uid=tour_uid,
        current_snapshot=current_snapshot,
        prev_snapshot=prev_snapshot,
        budget_result=budget_result,
        existing_alert_keys=existing_keys,
    )

    assert len(alerts) == 0
