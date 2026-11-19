from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class MemberCostItem(BaseModel):
    role: str = Field(..., description="成員角色，如 adult, senior, child, infant")
    count: int = Field(..., description="人數")
    unit_price: int = Field(..., description="每人費用（TWD）")
    subtotal: int = Field(..., description="小計金額（TWD）")
    note: str = Field("", description="計價說明與備註")
    is_estimated: bool = Field(False, description="是否包含預設計價補位")


class CostBreakdown(BaseModel):
    adult_total: int = Field(0, description="一般成人團費總額")
    senior_total: int = Field(0, description="長輩團費總額")
    child_with_bed_total: int = Field(0, description="佔床兒童團費總額")
    child_no_bed_total: int = Field(0, description="不佔床兒童團費總額")
    infant_total: int = Field(0, description="嬰兒團費總額")
    tips_total: int = Field(0, description="領隊導遊小費總額")
    single_supplement_total: int = Field(0, description="單人房差總額")
    items: List[MemberCostItem] = Field(default_factory=list, description="各成員費用明細表")


class FamilyBudgetResult(BaseModel):
    tour_uid: str = Field(..., description="行程唯一代碼 {agency}:{tour_code}:{departure_date}")
    grand_total_twd: int = Field(..., description="全家族含小費與房差真實總價")
    avg_cost_per_person_twd: int = Field(..., description="全家族平均每人花費")
    total_family_members: int = Field(..., description="全家族總人數")
    total_flight_seats_needed: int = Field(..., description="全家族所需機位總數")
    total_beds_needed: int = Field(..., description="全家族所需床位總數")
    seat_status: Literal["SUFFICIENT", "INSUFFICIENT", "UNKNOWN"] = Field(
        "UNKNOWN", description="機位是否足夠容納全家族"
    )
    breakdown: CostBreakdown = Field(default_factory=CostBreakdown, description="逐項費用明細")
    is_estimated: bool = Field(False, description="是否包含估算補位數值")
    assumptions: List[str] = Field(default_factory=list, description="估算補位假設說明清單")
    risk_warnings: List[str] = Field(default_factory=list, description="風險與特殊限制標籤清單")
    composite_score: float = Field(0.0, description="綜合推薦評分")
    estimated_land_cost_per_adult: Optional[int] = Field(
        None, description="扣除直飛機票基準價後之估計每人地上成本"
    )


class AlertEvent(BaseModel):
    alert_key: str = Field(..., description="唯一去重鍵，如 PRICE_DROP:{tour_uid}:{new_price}")
    alert_type: Literal[
        "PRICE_DROP",
        "LOW_SEATS",
        "SEAT_CRITICAL",
        "NEW_HIGH_VALUE_TOUR",
        "NEW_TOUR",
        "AGENCY_CRAWL_ERROR",
    ] = Field(..., description="告警事件類型")
    tour_uid: Optional[str] = Field(None, description="關聯團次 UID")
    priority: Literal["高", "中高", "中", "維運", "LOW", "MEDIUM", "HIGH"] = Field("中", description="告警優先級")
    message: str = Field(..., description="告警通知訊息內容")
    details: dict = Field(default_factory=dict, description="結構化附加資訊")
    created_at: Optional[str] = Field(None, description="產生時間戳 (ISO8601)")


class RankedTourResult(BaseModel):
    tour_uid: str
    agency: str
    tour_name: str
    departure_date: str
    days: int
    departure_airport: str
    adult_price: Optional[int] = None
    seats_available: Optional[int] = None
    detail_url: str
    budget: FamilyBudgetResult
    composite_score: float
