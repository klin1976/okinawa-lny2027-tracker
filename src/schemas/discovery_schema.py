from typing import Literal, Optional
from pydantic import BaseModel, Field


class TourListItem(BaseModel):
    agency: Literal["可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊"] = Field(
        ..., description="旅行社名稱"
    )
    tour_code: str = Field(..., description="唯一識別碼（團號/產品代碼，用於 DB 去重）")
    tour_name: str = Field(..., description="行程標題")
    departure_date: str = Field(..., description="出發日期 YYYY-MM-DD")
    days: int = Field(..., le=5, description="行程天數，過濾器硬限制 <= 5")
    departure_airport: str = Field(..., description="出發機場代碼，如 TPE / KHH / RMQ / OTHER")
    adult_price: Optional[int] = Field(None, description="清單頁即時成人團費（台幣整數）")
    seats_available: Optional[int] = Field(None, description="清單頁即時可售機位")
    status: str = Field("未知", description="可報名 / 保證出團 / 候補 / 滿團 / 未知")
    detail_url: str = Field(..., description="完整行程詳情頁網址")
    raw_hash: str = Field("", description="清單關鍵欄位雜湊值，用於判斷是否異動")
