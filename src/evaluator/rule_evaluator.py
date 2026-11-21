from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.schemas.budget_schema import FamilyBudgetResult
from src.schemas.tour_schema import TourPackage
from src.schemas.trip_schema import TripConfig, TripScoringRules

DEFAULT_SHOPPING_KEYWORDS = [
    "免稅店",
    "購物站",
    "光伸",
    "人蔘",
    "保肝",
    "乳膠",
    "珍珠",
    "彩妝",
]


@dataclass
class EvaluationResult:
    is_passed: bool
    score: float
    tags: List[str] = field(default_factory=list)
    passed_rules: List[str] = field(default_factory=list)
    failed_rules: List[str] = field(default_factory=list)


class RuleEvaluator:
    """對齊 tech-training-radar 的業務規則過濾、0~100 品質評分與標籤化引擎。"""

    @staticmethod
    def _detect_shopping_stop(
        tour: TourPackage, shopping_keywords: List[str]
    ) -> bool:
        if tour.comparison_flags.has_shopping_station:
            return True
        for day in tour.itinerary:
            for attr in day.attractions:
                if attr.is_shopping_stop:
                    return True
                if any(kw.lower() in attr.name.lower() for kw in shopping_keywords):
                    return True
        return False

    @classmethod
    def evaluate(
        cls,
        tour: TourPackage,
        budget: FamilyBudgetResult,
        trip_config: Optional[TripConfig] = None,
    ) -> EvaluationResult:
        rules = trip_config.scoring_rules if trip_config else TripScoringRules()
        shopping_keywords = (
            trip_config.destination.shopping_stop_keywords
            if trip_config
            else DEFAULT_SHOPPING_KEYWORDS
        )

        is_passed = True
        score = 55.0
        tags: List[str] = []
        passed_rules: List[str] = []
        failed_rules: List[str] = []

        # 1. 天數與排除關鍵字檢核
        if trip_config is not None:
            if trip_config.schedule.min_days <= tour.days <= trip_config.schedule.max_days:
                passed_rules.append(f"天數符合({tour.days}天)")
            else:
                failed_rules.append(
                    f"天數超出({tour.days}天，限{trip_config.schedule.min_days}~{trip_config.schedule.max_days}天)"
                )
                is_passed = False

            ex_kws = trip_config.destination.exclude_keywords
            if ex_kws and any(ex.lower() in tour.tour_name.lower() for ex in ex_kws):
                failed_rules.append("命中排除關鍵字")
                tags.append("排除項目")
                is_passed = False

        # 2. 購物站檢核
        has_shopping = cls._detect_shopping_stop(tour, shopping_keywords)
        if not has_shopping:
            passed_rules.append("無購物站")
            tags.append("無購物")
            score += rules.avoid_shopping_stop_bonus
        else:
            failed_rules.append("含購物站")
            tags.append("含購物站")

        # 3. 機位充足度檢核
        if budget.seat_status == "SUFFICIENT":
            passed_rules.append("機位充足")
            tags.append("機位充足")
            score += 5.0
        elif budget.seat_status == "INSUFFICIENT":
            failed_rules.append("機位不足")
            tags.append("機位不足")
            score -= 30.0
            is_passed = False
        else:
            tags.append("機位待確認")

        # 4. 目標總預算檢核
        if trip_config and trip_config.party.target_total_budget_twd and budget.grand_total_twd > 0:
            target = trip_config.party.target_total_budget_twd
            if budget.grand_total_twd <= target:
                passed_rules.append("低於目標預算")
                tags.append("低於目標預算")
                score += rules.below_budget_bonus
            else:
                failed_rules.append("超出目標預算")
                tags.append("超出預算")

        # 5. 出團狀態檢核
        if tour.status == "保證出團":
            passed_rules.append("保證出團")
            tags.append("保證出團")
            score += rules.prefer_guaranteed_departure_bonus
        elif tour.status == "滿團":
            failed_rules.append("已滿團")
            tags.append("已滿團")
            score -= 25.0
            is_passed = False

        # 6. 直飛與航班時段
        is_direct = tour.flights.is_direct
        if is_direct is None and tour.flights.outbound is not None:
            if tour.flights.outbound.stops == 0:
                is_direct = True
        if is_direct:
            passed_rules.append("直飛航班")
            tags.append("直飛")
            score += rules.prefer_direct_flight

        if tour.flights.time_band in {"早去晚回", "早去午回"}:
            passed_rules.append(f"時段佳({tour.flights.time_band})")
            tags.append(tour.flights.time_band)
            score += rules.early_out_late_back_bonus

        # 7. 連住與親子友善
        if tour.comparison_flags.no_hotel_change:
            passed_rules.append("連住不換飯店")
            tags.append("連住不換飯店")
            score += rules.no_hotel_change_bonus

        if tour.comparison_flags.kid_friendly_tags:
            for k_tag in tour.comparison_flags.kid_friendly_tags[:3]:
                tags.append(k_tag)
            score += min(
                len(tour.comparison_flags.kid_friendly_tags) * 3,
                rules.kid_friendly_attraction_bonus,
            )

        # 8. 高齡限制與自理餐罰則
        if any("長輩規定" in w or "親友陪同" in w for w in budget.risk_warnings):
            score += rules.senior_restriction_penalty
            tags.append("留意高齡條款")

        if tour.comparison_flags.total_self_paid_meals > 4:
            score += rules.too_many_self_paid_meals_penalty
            tags.append("自理餐較多")

        final_score = max(0.0, min(100.0, round(score, 1)))

        # 標籤去重並維持順序
        unique_tags = list(dict.fromkeys(tags))

        # 同步寫回 TourPackage 評估欄位
        tour.score = final_score
        tour.tags = unique_tags
        tour.passed_rules = passed_rules
        tour.failed_rules = failed_rules

        return EvaluationResult(
            is_passed=is_passed,
            score=final_score,
            tags=unique_tags,
            passed_rules=passed_rules,
            failed_rules=failed_rules,
        )
