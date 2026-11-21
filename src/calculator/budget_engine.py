from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from src.schemas.budget_schema import CostBreakdown, FamilyBudgetResult, MemberCostItem
from src.schemas.tour_schema import TourPackage
from src.schemas.trip_schema import TripConfig

DEFAULT_PROFILE_PATH = Path("config/family_profile.yaml")


class BudgetEngine:
    def __init__(
        self,
        profile_data_or_path: Optional[Union[str, Path, Dict[str, Any], TripConfig]] = None,
    ):
        if isinstance(profile_data_or_path, TripConfig):
            base_profile: Dict[str, Any] = {}
            ref = profile_data_or_path.party.family_profile_ref
            if ref and Path(ref).exists():
                with open(ref, "r", encoding="utf-8") as f:
                    base_profile = yaml.safe_load(f) or {}
            elif DEFAULT_PROFILE_PATH.exists():
                with open(DEFAULT_PROFILE_PATH, "r", encoding="utf-8") as f:
                    base_profile = yaml.safe_load(f) or {}
            self.profile = profile_data_or_path.build_effective_profile(base_profile)
        elif isinstance(profile_data_or_path, dict):
            self.profile = profile_data_or_path
        elif profile_data_or_path is not None:
            with open(profile_data_or_path, "r", encoding="utf-8") as f:
                self.profile = yaml.safe_load(f) or {}
        else:
            if DEFAULT_PROFILE_PATH.exists():
                with open(DEFAULT_PROFILE_PATH, "r", encoding="utf-8") as f:
                    self.profile = yaml.safe_load(f) or {}
            else:
                self.profile = {}

        self.members = self.profile.get("members", [])
        self.defaults = self.profile.get("defaults", {})
        self.rooming = self.profile.get("rooming", {})
        self.scoring_weights = self.profile.get("scoring_weights", {})
        self.child_bed_age_threshold = int(
            self.profile.get(
                "child_bed_age_threshold",
                self.defaults.get("child_bed_age_threshold", 6),
            )
        )

    def calculate_demands(self) -> Dict[str, int]:
        total_seats = 0
        total_beds = 0
        total_pax = 0

        for member in self.members:
            count = member.get("count", 1)
            age = member.get("age")
            require_bed = member.get("require_bed", True)
            require_flight_seat = member.get("require_flight_seat", True)

            total_pax += count
            if require_flight_seat:
                total_seats += count

            # 依旅遊專案國別／飯店規定之強制佔床年齡門檻判斷（日本多為 6 歲，歐美可設 12 歲）
            if require_bed or (age is not None and age >= self.child_bed_age_threshold):
                total_beds += count

        return {
            "total_pax": total_pax,
            "total_flight_seats_needed": total_seats,
            "total_beds_needed": total_beds,
        }

    def calculate(
        self,
        tour: TourPackage,
        benchmark_flight_min_price: Optional[int] = None,
    ) -> FamilyBudgetResult:
        demands = self.calculate_demands()
        total_pax = demands["total_pax"]
        total_seats_needed = demands["total_flight_seats_needed"]
        total_beds_needed = demands["total_beds_needed"]

        tour_uid = f"{tour.agency}:{tour.tour_code or 'UNKNOWN'}:{tour.departure_date or 'NODATE'}"
        pricing = tour.pricing
        adult_twin_price = pricing.adult_twin_price or 0

        is_estimated = False
        assumptions: List[str] = []
        risk_warnings: List[str] = []
        cost_items: List[MemberCostItem] = []

        if adult_twin_price == 0:
            is_estimated = True
            assumptions.append("行程未標註成人雙人房價格，基礎團費暫估為 0")

        # 1. 機位充足度檢核
        seats_available = tour.seats_available
        if seats_available is not None:
            if seats_available < total_seats_needed:
                seat_status = "INSUFFICIENT"
                risk_warnings.append(
                    f"剩餘機位僅 {seats_available} 位，不足家族所需 {total_seats_needed} 席"
                )
            else:
                seat_status = "SUFFICIENT"
        else:
            seat_status = "UNKNOWN"

        # 2. 各成員團費計算
        adult_total = 0
        senior_total = 0
        child_with_bed_total = 0
        child_no_bed_total = 0
        infant_total = 0

        child_pricing = pricing.child_pricing
        senior_policy = pricing.senior_policy

        for member in self.members:
            role = member.get("role", "adult")
            count = member.get("count", 1)
            age = member.get("age")
            declared_require_bed = member.get("require_bed", True)

            # 依專案強制佔床年齡門檻進行防護
            actual_require_bed = declared_require_bed or (
                age is not None and age >= self.child_bed_age_threshold
            )

            if role == "adult":
                unit_price = adult_twin_price
                subtotal = unit_price * count
                adult_total += subtotal
                cost_items.append(
                    MemberCostItem(
                        role="adult",
                        count=count,
                        unit_price=unit_price,
                        subtotal=subtotal,
                        note="成人雙人房佔床費用",
                        is_estimated=False,
                    )
                )

            elif role == "senior":
                adjustment = senior_policy.senior_price_adjustment or 0
                unit_price = max(0, adult_twin_price + adjustment)
                subtotal = unit_price * count
                senior_total += subtotal

                threshold = senior_policy.senior_age_threshold or 70
                if age is not None and age >= threshold:
                    if senior_policy.senior_companion_rule:
                        risk_warnings.append(f"長輩規定：{senior_policy.senior_companion_rule}")
                    else:
                        risk_warnings.append(f"{age}歲長輩參團須留意親友陪同條款")
                    if senior_policy.senior_insurance_note:
                        risk_warnings.append(f"長輩保險：{senior_policy.senior_insurance_note}")

                cost_items.append(
                    MemberCostItem(
                        role="senior",
                        count=count,
                        unit_price=unit_price,
                        subtotal=subtotal,
                        note=f"長輩費用（價差調整: {adjustment}）",
                        is_estimated=False,
                    )
                )

            elif role == "child":
                if actual_require_bed:
                    estimated_item = False
                    if child_pricing.child_with_bed_price is not None:
                        unit_price = child_pricing.child_with_bed_price
                        note = "兒童佔床專屬報價"
                    elif child_pricing.child_with_bed_diff is not None:
                        unit_price = max(0, adult_twin_price + child_pricing.child_with_bed_diff)
                        note = f"兒童佔床價差計算（{child_pricing.child_with_bed_diff}）"
                    else:
                        unit_price = adult_twin_price
                        note = "兒童佔床未特別報價，採成人同價估算"
                        assumptions.append("兒童佔床未標價，採成人同價估算")
                        estimated_item = True
                        is_estimated = True

                    subtotal = unit_price * count
                    child_with_bed_total += subtotal
                    cost_items.append(
                        MemberCostItem(
                            role="child_with_bed",
                            count=count,
                            unit_price=unit_price,
                            subtotal=subtotal,
                            note=note,
                            is_estimated=estimated_item,
                        )
                    )
                else:
                    estimated_item = False
                    if child_pricing.child_no_bed_price is not None:
                        unit_price = child_pricing.child_no_bed_price
                        note = "兒童不佔床專屬報價"
                    elif child_pricing.child_no_bed_diff is not None:
                        unit_price = max(0, adult_twin_price + child_pricing.child_no_bed_diff)
                        note = f"兒童不佔床價差計算（{child_pricing.child_no_bed_diff}）"
                    else:
                        fallback_diff = self.defaults.get("fallback_child_no_bed_diff", -3000)
                        unit_price = max(0, adult_twin_price + fallback_diff)
                        note = f"兒童不佔床未標價，以預設價差 {fallback_diff} 估算"
                        assumptions.append(f"兒童不佔床未標價，採預設價差 {fallback_diff} 估算")
                        estimated_item = True
                        is_estimated = True

                    subtotal = unit_price * count
                    child_no_bed_total += subtotal
                    cost_items.append(
                        MemberCostItem(
                            role="child_no_bed",
                            count=count,
                            unit_price=unit_price,
                            subtotal=subtotal,
                            note=note,
                            is_estimated=estimated_item,
                        )
                    )

            elif role == "infant":
                estimated_item = False
                if child_pricing.infant_under_2_price is not None:
                    unit_price = child_pricing.infant_under_2_price
                    note = "未滿2歲嬰兒報價"
                else:
                    fallback_infant = self.defaults.get("fallback_infant_price", 6000)
                    unit_price = fallback_infant
                    note = f"嬰兒未標價，以預設 {fallback_infant} 估算"
                    assumptions.append(f"嬰兒未標價，採預設 {fallback_infant} 估算")
                    estimated_item = True
                    is_estimated = True

                subtotal = unit_price * count
                infant_total += subtotal
                cost_items.append(
                    MemberCostItem(
                        role="infant",
                        count=count,
                        unit_price=unit_price,
                        subtotal=subtotal,
                        note=note,
                        is_estimated=estimated_item,
                    )
                )

        # 3. 領隊導遊司機小費計算
        tip_per_day = pricing.tip_per_day_twd or self.defaults.get("tip_per_day_twd", 300)
        tip_exempt_age = self.defaults.get("tip_exempt_under_age", 2)

        tip_pax_count = 0
        for m in self.members:
            count = m.get("count", 1)
            age = m.get("age")
            if age is None or age >= tip_exempt_age:
                tip_pax_count += count

        tips_total = tip_per_day * tour.days * tip_pax_count
        cost_items.append(
            MemberCostItem(
                role="service_tips",
                count=tip_pax_count,
                unit_price=tip_per_day * tour.days,
                subtotal=tips_total,
                note=f"領隊導遊小費（每日 {tip_per_day} 元 × {tour.days} 天 × {tip_pax_count} 人）",
                is_estimated=(pricing.tip_per_day_twd is None),
            )
        )
        if pricing.tip_per_day_twd is None:
            is_estimated = True
            assumptions.append(f"行程未載明每日小費，採專案預設每日 {tip_per_day} 元估算")

        # 4. 單人房差檢核
        single_supplement_total = 0
        prefer_triple = self.rooming.get("prefer_triple_room_for_odd_pax", True)
        fallback_single_supplement = self.defaults.get("fallback_single_room_supplement", 12000)
        actual_supplement = pricing.single_room_supplement or fallback_single_supplement

        if total_beds_needed % 2 == 1:
            triple_policy = (pricing.triple_room_policy or "").lower()
            no_triple_keywords = ["無法加床", "無三人房", "不提供三人房", "不可加床", "無法提供加床"]
            cannot_triple = any(k in triple_policy for k in no_triple_keywords)

            if cannot_triple or not prefer_triple:
                single_supplement_total = actual_supplement
                assumptions.append("佔床人數為奇數且不提供三人房/加床，加計單人房差")
                cost_items.append(
                    MemberCostItem(
                        role="single_supplement",
                        count=1,
                        unit_price=actual_supplement,
                        subtotal=actual_supplement,
                        note="單人房差額（無法安排三人房）",
                        is_estimated=(pricing.single_room_supplement is None),
                    )
                )
                if pricing.single_room_supplement is None:
                    is_estimated = True
            else:
                single_supplement_total = 0
                assumptions.append("佔床總人數為奇數，以雙人房搭配 1 間三人房/加床估算（免收單人房差）")

        # 5. 總計與人均
        grand_total = (
            adult_total
            + senior_total
            + child_with_bed_total
            + child_no_bed_total
            + infant_total
            + tips_total
            + single_supplement_total
        )
        avg_cost = round(grand_total / total_pax) if total_pax > 0 else grand_total

        # 6. 地上成本對照
        land_cost = None
        if benchmark_flight_min_price is not None:
            land_cost = adult_twin_price - benchmark_flight_min_price

        # 7. 風險標籤（去地域化）
        flags = tour.comparison_flags
        if flags.has_shopping_station:
            risk_warnings.append("全行程包含免稅／購物站行程")
        if flags.total_self_paid_meals >= 4:
            risk_warnings.append(f"自理餐偏多（總計 {flags.total_self_paid_meals} 餐須自理）")
        if tour.flights.outbound and tour.flights.outbound.is_charter_flight:
            risk_warnings.append("去程為包機/包銷機位，開票後不可退改")
        surcharge_note = pricing.peak_season_surcharge_note or pricing.lny_surcharge_note
        if surcharge_note:
            risk_warnings.append(surcharge_note)

        # 8. 綜合性價比評分
        score = 80.0
        w = self.scoring_weights
        if not flags.has_shopping_station:
            score += w.get("avoid_shopping_stop_bonus", 15)
        if flags.no_hotel_change:
            score += w.get("no_hotel_change_bonus", 10)
        if tour.flights.time_band in ["早去晚回", "早去午回"]:
            score += w.get("early_out_late_back_bonus", 12)
        if flags.kid_friendly_tags:
            score += min(len(flags.kid_friendly_tags) * 3, w.get("kid_friendly_attraction_bonus", 8))
        if any("長輩規定" in w_item or "親友陪同" in w_item for w_item in risk_warnings):
            score += w.get("senior_restriction_penalty", -5)
        if flags.total_self_paid_meals > 4:
            score += w.get("too_many_self_paid_meals_penalty", -5)
        if seat_status == "INSUFFICIENT":
            score -= 30.0

        score = max(0.0, min(100.0, round(score, 1)))

        breakdown = CostBreakdown(
            adult_total=adult_total,
            senior_total=senior_total,
            child_with_bed_total=child_with_bed_total,
            child_no_bed_total=child_no_bed_total,
            infant_total=infant_total,
            tips_total=tips_total,
            single_supplement_total=single_supplement_total,
            items=cost_items,
        )

        return FamilyBudgetResult(
            tour_uid=tour_uid,
            grand_total_twd=grand_total,
            avg_cost_per_person_twd=avg_cost,
            total_family_members=total_pax,
            total_flight_seats_needed=total_seats_needed,
            total_beds_needed=total_beds_needed,
            seat_status=seat_status,
            breakdown=breakdown,
            is_estimated=is_estimated,
            assumptions=assumptions,
            risk_warnings=risk_warnings,
            composite_score=score,
            estimated_land_cost_per_adult=land_cost,
        )
