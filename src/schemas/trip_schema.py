from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DestinationConfig(BaseModel):
    country: str = Field(..., description="目的地國家，例如：日本、韓國、奧地利/捷克")
    region_name: str = Field(..., description="目的地城市或區域名稱，例如：沖繩、北海道、首爾、奧捷")
    search_keywords: List[str] = Field(..., min_length=1, description="傳送給旅行社搜尋的關鍵字清單")
    exclude_keywords: List[str] = Field(
        default_factory=list, description="標題包含這些關鍵字時予以排除（如：郵輪、機加酒）"
    )
    airports: List[str] = Field(
        default_factory=list, description="目的地主要機場 IATA 代碼清單（如 ['OKA']、['CTS', 'HKD']）"
    )
    shopping_stop_keywords: List[str] = Field(
        default_factory=lambda: ["免稅店", "購物站", "光伸", "人蔘", "保肝", "乳膠", "珍珠"],
        description="用以偵測行程是否含購物站的關鍵字清單",
    )


class ScheduleConfig(BaseModel):
    departure_date_start: str = Field(..., description="最早出發日期 YYYY-MM-DD")
    departure_date_end: str = Field(..., description="最晚出發日期 YYYY-MM-DD")
    min_days: int = Field(1, ge=1, le=30, description="行程最少天數")
    max_days: int = Field(30, ge=1, le=30, description="行程最多天數")
    is_peak_season: bool = Field(False, description="是否屬於連假或旅遊旺季")
    peak_season_label: str = Field("", description="旺季說明標籤，例如：2027 春節連假、暑假旺季")


class FlightBenchmarkConfig(BaseModel):
    enabled: bool = Field(True, description="是否啟用同期機票基準價查詢")
    origins: List[str] = Field(default_factory=lambda: ["TPE", "KHH"], description="台灣出發機場代碼")
    sample_depart_date: Optional[str] = Field(None, description="機票基準查詢去程日期 YYYY-MM-DD")
    sample_return_date: Optional[str] = Field(None, description="機票基準查詢回程日期 YYYY-MM-DD")
    max_stops: int = Field(0, ge=0, le=2, description="最大轉機次數（短程直飛為 0，長程線可設 1）")


class TripScoringRules(BaseModel):
    prefer_direct_flight: int = Field(10, description="直飛航班加分")
    avoid_shopping_stop_bonus: int = Field(15, description="無購物站加分")
    no_hotel_change_bonus: int = Field(10, description="全程連住不換飯店加分")
    early_out_late_back_bonus: int = Field(12, description="早去晚回／早去午回佳時段加分")
    prefer_guaranteed_departure_bonus: int = Field(8, description="保證出團加分")
    kid_friendly_attraction_bonus: int = Field(8, description="親子友善景點加分上限")
    senior_restriction_penalty: int = Field(-5, description="高齡參團限制扣分")
    too_many_self_paid_meals_penalty: int = Field(-5, description="過多自理餐扣分")
    below_budget_bonus: int = Field(10, description="家族總預算低於目標預算加分")


class PartyOverrides(BaseModel):
    family_profile_ref: Optional[str] = Field(
        "config/family_profile.yaml", description="基礎成員結構設定檔路徑"
    )
    members: Optional[List[Dict[str, Any]]] = Field(
        None, description="若不沿用基礎成員檔，可在此直接覆寫同行成員名單"
    )
    child_bed_age_threshold: int = Field(
        6, ge=0, le=18, description="兒童強制佔床年齡門檻（日本/韓國多為 6，歐美線可設 12）"
    )
    tip_per_day_twd: Optional[int] = Field(None, ge=0, description="覆寫每日領隊導遊小費（台幣）")
    tip_exempt_under_age: Optional[int] = Field(None, ge=0, description="覆寫免收小費年齡門檻")
    target_total_budget_twd: Optional[int] = Field(None, ge=0, description="家族目標總預算上限（台幣）")
    price_drop_per_adult_twd: Optional[int] = Field(None, ge=0, description="單人降價告警門檻（台幣）")
    price_drop_family_total_twd: Optional[int] = Field(None, ge=0, description="家族總價降價告警門檻（台幣）")
    seat_buffer: Optional[int] = Field(None, ge=0, description="低機位預警安全緩衝席數")


class TripConfig(BaseModel):
    """通用多目的地旅遊追蹤專案設定模型。"""

    trip_id: str = Field(..., min_length=1, description="唯一旅遊專案代碼，如 okinawa_lny2027")
    trip_name: str = Field(..., min_length=1, description="旅遊專案顯示名稱")
    enabled: bool = Field(True, description="是否啟用自動巡檢")
    destination: DestinationConfig
    schedule: ScheduleConfig
    flight_benchmark: FlightBenchmarkConfig = Field(default_factory=FlightBenchmarkConfig)
    party: PartyOverrides = Field(default_factory=PartyOverrides)
    scoring_rules: TripScoringRules = Field(default_factory=TripScoringRules)

    def to_common_filters(self) -> Dict[str, Any]:
        """轉換為 BaseAgencyAdapter 可直接消費的過濾條件字典。"""
        return {
            "trip_id": self.trip_id,
            "destination_keywords": list(self.destination.search_keywords),
            "exclude_keywords": list(self.destination.exclude_keywords),
            "departure_date_range": {
                "start": self.schedule.departure_date_start,
                "end": self.schedule.departure_date_end,
            },
            "min_days": self.schedule.min_days,
            "max_days": self.schedule.max_days,
        }

    def build_effective_profile(self, base_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """將基礎家族設定與本旅遊專案的國別/預算覆寫合併為完整計算設定。"""
        profile: Dict[str, Any] = copy.deepcopy(base_profile) if base_profile else {}
        profile["trip_id"] = self.trip_id
        profile["trip_name"] = self.trip_name
        profile["family_name"] = profile.get("family_name") or self.trip_name

        if self.party.members is not None:
            profile["members"] = copy.deepcopy(self.party.members)

        profile["child_bed_age_threshold"] = self.party.child_bed_age_threshold

        defaults = dict(profile.get("defaults") or {})
        defaults["child_bed_age_threshold"] = self.party.child_bed_age_threshold
        if self.party.tip_per_day_twd is not None:
            defaults["tip_per_day_twd"] = self.party.tip_per_day_twd
        if self.party.tip_exempt_under_age is not None:
            defaults["tip_exempt_under_age"] = self.party.tip_exempt_under_age
        profile["defaults"] = defaults

        if self.party.target_total_budget_twd is not None:
            profile["target_total_budget_twd"] = self.party.target_total_budget_twd

        alerts = dict(profile.get("alerts") or {})
        if self.party.price_drop_per_adult_twd is not None:
            alerts["price_drop_per_adult_twd"] = self.party.price_drop_per_adult_twd
        if self.party.price_drop_family_total_twd is not None:
            alerts["price_drop_family_total_twd"] = self.party.price_drop_family_total_twd
        if self.party.seat_buffer is not None:
            alerts["seat_buffer"] = self.party.seat_buffer
        profile["alerts"] = alerts

        scoring_weights = dict(profile.get("scoring_weights") or {})
        scoring_weights.update(self.scoring_rules.model_dump())
        profile["scoring_weights"] = scoring_weights

        profile["destination"] = self.destination.model_dump()
        profile["schedule"] = self.schedule.model_dump()
        return profile
