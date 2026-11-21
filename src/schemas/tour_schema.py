from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class FlightLeg(BaseModel):
    airline: str = Field(..., description="航空公司名稱，例如中華航空、長榮航空、星宇航空、阿聯酋航空")
    flight_number: Optional[str] = Field(None, description="航班編號，例如 CI120、JX870、BR061")
    is_lcc: bool = Field(False, description="是否為廉價航空（如虎航、樂桃、酷航、德威等）")
    is_charter_flight: bool = Field(False, description="是否標註為包機、加班機或團體包銷機位")
    departure_airport: str = Field(..., description="出發機場 IATA 代碼，例如 TPE、KHH、RMQ、TSA")
    arrival_airport: str = Field(..., description="抵達機場 IATA 代碼，例如 OKA、CTS、ICN、VIE")
    departure_time: Optional[str] = Field(None, description="出發時間 HH:MM（24小時制）")
    arrival_time: Optional[str] = Field(None, description="抵達時間 HH:MM（24小時制）")
    checked_baggage_kg: Optional[int] = Field(None, description="免費託運行李公斤數（若頁面未標明則為 null）")
    meal_included: Optional[bool] = Field(None, description="是否含機上餐食")
    stops: Optional[int] = Field(None, description="轉機次數（0 為直飛）")


class FlightSummary(BaseModel):
    outbound: Optional[FlightLeg] = Field(None, description="去程航班資訊")
    inbound: Optional[FlightLeg] = Field(None, description="回程航班資訊")
    is_direct: Optional[bool] = Field(None, description="去回程是否皆為直飛")
    time_band: Literal["早去晚回", "早去午回", "午去晚回", "午去午回", "晚去早回", "晚去晚回", "其他"] = Field(
        "其他", description="航班時段綜合評價（11:59前出發算早去，17:00後回程算晚回）"
    )
    flight_notes: Optional[str] = Field(None, description="航班相關備註（如包機時間可能異動、開票後不可退改）")


class ChildPricing(BaseModel):
    child_with_bed_price: Optional[int] = Field(None, description="兒童佔床報價（台幣），若與成人同價請填入成人價")
    child_with_bed_diff: Optional[int] = Field(None, description="兒童佔床與成人價差（負數代表減價，如 -2000）")
    child_no_bed_price: Optional[int] = Field(None, description="兒童不佔床報價（台幣）")
    child_no_bed_diff: Optional[int] = Field(None, description="兒童不佔床與成人價差（如 -4000）")
    child_no_bed_age_rule: Optional[str] = Field(
        None, description="兒童不佔床適用年齡規定（例如：滿2歲未滿6歲可不佔床，6歲以上強制佔床；或歐美滿12歲）"
    )
    infant_under_2_price: Optional[int] = Field(None, description="未滿2歲嬰兒報價（台幣，含稅不佔位）")


class SeniorAndSpecialPolicy(BaseModel):
    senior_price_adjustment: Optional[int] = Field(
        None, description="長輩敬老優惠（填負數）或高齡附加費用（填正數），無特別價差填 null"
    )
    senior_age_threshold: Optional[int] = Field(None, description="條款中提及的高齡門檻歲數（常見為 70 或 75 歲）")
    senior_companion_rule: Optional[str] = Field(
        None, description="高齡參團規定（如：滿70歲須有親友陪同、80歲以上須填健康聲明書）"
    )
    senior_insurance_note: Optional[str] = Field(
        None, description="高齡旅客旅責險或意外醫療保額限制／加保說明"
    )


class PricingDetail(BaseModel):
    currency: str = Field("TWD", description="幣別，預設 TWD")
    adult_twin_price: Optional[int] = Field(None, description="成人雙人房佔床每人團費（台幣整數）")
    tax_included: bool = Field(True, description="報價是否已含機場稅與燃油附加費")
    peak_season_surcharge_included: bool = Field(True, description="報價是否已含連假／旺季加價")
    peak_season_surcharge_note: Optional[str] = Field(None, description="旺季特殊加價、高訂金或嚴格取消費規則說明")
    # 向後相容舊欄位
    lny_surcharge_included: bool = Field(True, description="向後相容欄位：報價是否已含春節旺季加價")
    lny_surcharge_note: Optional[str] = Field(None, description="向後相容欄位：春節特殊加價說明")
    child_pricing: ChildPricing = Field(default_factory=ChildPricing)
    senior_policy: SeniorAndSpecialPolicy = Field(default_factory=SeniorAndSpecialPolicy)
    tip_per_day_twd: Optional[int] = Field(None, description="領隊導遊司機小費（台幣／每日，日本團常見 300、歐洲常見 400~500）")
    single_room_supplement: Optional[int] = Field(None, description="單人房差額（台幣）")
    triple_room_policy: Optional[str] = Field(None, description="三人房或加床規定（如提供沙發床、行軍床或無法加床）")
    deposit_per_person: Optional[int] = Field(None, description="報名訂金（台幣／每人）")
    early_bird_or_promo: Optional[str] = Field(None, description="早鳥折扣、第二人減價或聯名卡優惠說明")

    @model_validator(mode="after")
    def _sync_peak_surcharge_aliases(self) -> "PricingDetail":
        if self.peak_season_surcharge_note is None and self.lny_surcharge_note is not None:
            self.peak_season_surcharge_note = self.lny_surcharge_note
        elif self.lny_surcharge_note is None and self.peak_season_surcharge_note is not None:
            self.lny_surcharge_note = self.peak_season_surcharge_note
        if not self.lny_surcharge_included and self.peak_season_surcharge_included:
            self.peak_season_surcharge_included = False
        elif not self.peak_season_surcharge_included and self.lny_surcharge_included:
            self.lny_surcharge_included = False
        return self


class AttractionItem(BaseModel):
    name: str = Field(..., description="景點名稱，例如：美瑛青池、景福宮、庫倫洛夫小鎮、美麗海水族館")
    region: str = Field("未分類", description="景點所屬國家／城市或地理分區")
    admission_type: Literal["含門票", "免費/下車參觀", "車窗瀏覽", "自費", "未標明"] = Field(
        "未標明", description="門票包含狀態"
    )
    is_shopping_stop: bool = Field(False, description="是否為購物站（如免稅店、人蔘、保肝、乳膠、光伸免稅站等）")


class MealPlan(BaseModel):
    breakfast: str = Field("未標明", description="早餐安排（如：飯店內用、敬請自理）")
    lunch: str = Field("未標明", description="午餐安排（如：當地特色料理、方便遊玩敬請自理）")
    dinner: str = Field("未標明", description="晚餐安排（如：自助餐、敬請自理）")
    self_paid_meal_count: int = Field(0, description="當日須自理的餐數（0～3）")


class HotelStay(BaseModel):
    candidate_hotels: List[str] = Field(default_factory=list, description="當晚候選飯店名稱清單（拆開『或』字）")
    or_similar: bool = Field(False, description="頁面是否標註『或同級』")
    area: str = Field("其他", description="飯店所在區域或城市類型（如市區、溫泉區、渡假村）")
    is_beach_resort: bool = Field(False, description="是否屬於渡假村類型飯店")


class DailyItinerary(BaseModel):
    day_number: int = Field(..., ge=1, le=30, description="第幾天（1 至 30）")
    day_title: str = Field(..., description="當日行程標題摘要")
    is_free_day: bool = Field(False, description="當日是否為全日自由活動（無專車與導遊）")
    attractions: List[AttractionItem] = Field(default_factory=list, description="當日景點清單")
    meals: MealPlan = Field(default_factory=MealPlan)
    hotel: Optional[HotelStay] = Field(None, description="當晚住宿（最後一天返抵國門則為 null）")


class ComparisonFlags(BaseModel):
    has_shopping_station: bool = Field(False, description="全行程是否包含免稅／強制購物站")
    free_day_count: int = Field(0, description="全日自由活動天數")
    no_hotel_change: bool = Field(False, description="是否全程連住同一間飯店免搬行李")
    total_self_paid_meals: int = Field(0, description="全行程總計自理餐數")
    kid_friendly_tags: List[str] = Field(
        default_factory=list, description="適合兒童的亮點標籤（如：樂園、動物園、水族館、戲雪、溫泉）"
    )


class TourPackage(BaseModel):
    trip_id: str = Field("default", description="所屬旅遊專案 ID")
    destination_country: Optional[str] = Field(None, description="目的地國家")
    destination_region: Optional[str] = Field(None, description="目的地地區或城市")
    agency: Literal["可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊", "其他"] = Field(
        ..., description="旅行社名稱"
    )
    tour_code: Optional[str] = Field(None, description="團號或產品代碼")
    tour_name: str = Field(..., description="完整行程標題")
    source_url: Optional[str] = Field(None, description="原始抓取網址")
    tour_type: Literal["團體旅遊", "MiniTour/小包團", "機加酒自由行", "半自助"] = Field(
        "團體旅遊", description="行程運作型態"
    )
    days: int = Field(..., ge=1, le=30, description="行程總天數（支援 1 至 30 天）")
    nights: int = Field(..., ge=0, le=29, description="住宿晚數")
    departure_date: Optional[str] = Field(None, description="出發日期 YYYY-MM-DD")
    return_date: Optional[str] = Field(None, description="回程日期 YYYY-MM-DD")
    is_peak_season: bool = Field(False, description="出發或行程區間是否涵蓋連假或旺季")
    is_lny_2027_peak: bool = Field(False, description="向後相容欄位：是否涵蓋 2027 農曆春節連假")
    departure_airport: Literal["TPE", "KHH", "RMQ", "TSA", "OTHER"] = Field(
        "TPE", description="台灣出發機場代碼（TPE桃園、KHH高雄、RMQ台中、TSA松山）"
    )
    status: Literal["可報名", "保證出團", "候補", "滿團", "已截止", "未知"] = Field("未知", description="團位狀態")
    seats_available: Optional[int] = Field(None, description="剩餘可售機位數")
    min_pax_to_go: Optional[int] = Field(None, description="最低成行人數（如 16 人或 6 人）")
    flights: FlightSummary = Field(default_factory=FlightSummary)
    pricing: PricingDetail = Field(default_factory=PricingDetail)
    itinerary: List[DailyItinerary] = Field(default_factory=list, description="每日行程明細")
    comparison_flags: ComparisonFlags = Field(default_factory=ComparisonFlags)

    # RuleEvaluator 評估欄位
    score: float = Field(0.0, description="綜合評分 (0~100)")
    tags: List[str] = Field(default_factory=list, description="行程亮點與風險標籤")
    passed_rules: List[str] = Field(default_factory=list, description="通過的評估規則")
    failed_rules: List[str] = Field(default_factory=list, description="未通過的評估規則")

    @model_validator(mode="after")
    def _sync_peak_season_alias(self) -> "TourPackage":
        if self.is_lny_2027_peak and not self.is_peak_season:
            self.is_peak_season = True
        elif self.is_peak_season and not self.is_lny_2027_peak:
            self.is_lny_2027_peak = True
        return self


# 向後相容別名
OkinawaTourPackage = TourPackage
