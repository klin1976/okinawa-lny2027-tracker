from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from playwright.async_api import async_playwright

from src.discovery.base_adapter import BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem

logger = logging.getLogger(__name__)


class ColaAdapter(BaseAgencyAdapter):
    """可樂旅遊清單撈取 Adapter（支援 TourSearch AJAX JSON 與 Playwright 備援，含 HTTP 435 WAF 偵測）。"""

    agency_key = "cola"
    agency_name = "可樂旅遊"

    XHR_ENDPOINT = "https://www.colatour.com.tw/C10A_TourList/api/TourSearch"

    @staticmethod
    def _check_waf_block(status_code: Optional[int], body_text: str) -> None:
        if status_code == 435 or "網站連線異常" in body_text:
            raise RuntimeError(
                f"可樂旅遊遭 WAF 攔截 (HTTP {status_code or 'N/A'} / 網站連線異常)，請確認網路環境或啟用住宅代理"
            )

    async def _post_json(
        self,
        url: str,
        json_body: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        merged = {**self._default_headers(), **(headers or {})}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            resp = await client.post(url, json=json_body, headers=merged)
            self._check_waf_block(resp.status_code, resp.text)
            resp.raise_for_status()
            return resp.json()

    async def fetch_mode_b_playwright(self) -> List[TourListItem]:
        """Mode B Playwright 備援，於頁面載入時優先偵測 HTTP 435 / WAF 異常頁。"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="zh-TW",
                user_agent=self._default_headers()["User-Agent"],
            )
            page = await context.new_page()
            try:
                resp = await page.goto(
                    self.search_url,
                    wait_until="domcontentloaded",
                    timeout=int(self.timeout_seconds * 1000),
                )
                status = resp.status if resp else None
                html = await page.content()
                self._check_waf_block(status, html)
            finally:
                await browser.close()
        return await super().fetch_mode_b_playwright()

    def _build_payload(self, keyword: str = "", page_index: int = 1) -> Dict[str, Any]:
        start_date, end_date = self.get_default_query_date_range()
        return {
            "Keyword": keyword,
            "BeginDate": start_date,
            "EndDate": end_date,
            "MaxDays": self.get_max_days(),
            "PageIndex": page_index,
            "PageSize": 20,
        }

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        all_items: List[TourListItem] = []
        seen_keys: set[tuple[str, str]] = set()
        headers = {
            "Origin": "https://www.colatour.com.tw",
            "Referer": "https://www.colatour.com.tw/C10A_TourList/C10A01_Search.aspx",
        }
        keywords = self.get_search_keywords() or [""]
        for kw_idx, kw in enumerate(keywords):
            if kw_idx > 0:
                await self.jitter_sleep()
            for page_idx in range(1, 6):
                payload = await self._post_json(
                    self.XHR_ENDPOINT,
                    json_body=self._build_payload(keyword=kw, page_index=page_idx),
                    headers=headers,
                )
                items = self.parse_xhr_payload(payload)
                if not items:
                    break
                for item in items:
                    key = (item.tour_code, item.departure_date)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_items.append(item)
                if len(items) < 20:
                    break
                await self.jitter_sleep()
        return all_items

    def parse_xhr_payload(self, payload: Any) -> List[TourListItem]:
        if not isinstance(payload, dict):
            return []

        raw_list = (
            payload.get("TourList")
            or payload.get("Data", {}).get("TourList")
            or payload.get("ResultList")
            or payload.get("items")
            or []
        )
        if not isinstance(raw_list, list):
            return []

        min_days = self.get_min_days()
        max_days = self.get_max_days()
        results: List[TourListItem] = []

        for row in raw_list:
            if not isinstance(row, dict):
                continue
            tour_code = str(
                row.get("TourCode") or row.get("PatternNo") or row.get("GroupNo") or ""
            ).strip()
            tour_name = str(
                row.get("TourName") or row.get("PatternName") or row.get("Title") or ""
            ).strip()
            dep_date = self.normalize_date(row.get("TourDate") or row.get("BeginDate"))
            days = self.parse_int_safe(row.get("TourDays") or row.get("Days")) or 0

            if not (tour_code and tour_name and dep_date) or days < min_days or days > max_days:
                continue

            adult_price = self.parse_int_safe(
                row.get("Price") or row.get("AdultPrice") or row.get("SellPrice")
            )
            seats = self.parse_int_safe(
                row.get("RemainSeats") or row.get("SeatCount") or row.get("SeatsAvailable")
            )
            status = str(row.get("StatusName") or row.get("Status") or "未知").strip()
            if seats is not None and seats == 0 and status == "未知":
                status = "滿團"
            elif seats is not None and seats > 0 and status == "未知":
                status = "可報名"

            detail_url = str(row.get("DetailUrl") or "").strip()
            if not detail_url:
                slash_date = dep_date.replace("-", "/")
                detail_url = f"https://tour.colatour.com.tw/itinerary?TourCode={tour_code}&TourDate={slash_date}"
            elif detail_url.startswith("/"):
                detail_url = f"https://www.colatour.com.tw{detail_url}"

            airport = self.normalize_airport(
                row.get("DepartCity") or row.get("DepartureAirport"),
                tour_name,
            )
            raw_hash = self.compute_raw_hash(
                self.agency_name, tour_code, dep_date, adult_price, seats, status
            )
            results.append(
                TourListItem(
                    trip_id=self.trip_id,
                    agency=self.agency_name,
                    tour_code=tour_code,
                    tour_name=tour_name,
                    departure_date=dep_date,
                    days=days,
                    departure_airport=airport,
                    adult_price=adult_price,
                    seats_available=seats,
                    status=status,
                    detail_url=detail_url,
                    raw_hash=raw_hash,
                )
            )
        return results
