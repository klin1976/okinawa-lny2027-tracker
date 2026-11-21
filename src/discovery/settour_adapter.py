from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from src.discovery.base_adapter import BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem

logger = logging.getLogger(__name__)


class SettourAdapter(BaseAgencyAdapter):
    """東南旅遊清單撈取 Adapter（支援 prodSearch JSON 與 Playwright 備援，預設快速逾時 15s）。"""

    agency_key = "settour"
    agency_name = "東南旅遊"

    XHR_ENDPOINT = "https://trip.settour.com.tw/api/prodSearch"

    def __init__(
        self,
        agency_config: Optional[Dict[str, Any]] = None,
        common_filters: Optional[Dict[str, Any]] = None,
        concurrency_config: Optional[Dict[str, Any]] = None,
        trip_config: Optional[Any] = None,
        allow_playwright_fallback: bool = True,
    ):
        super().__init__(
            agency_config,
            common_filters,
            concurrency_config,
            trip_config=trip_config,
            allow_playwright_fallback=allow_playwright_fallback,
        )
        self.timeout_seconds = float((agency_config or {}).get("timeout_seconds", 15))

    async def _post_json(
        self,
        url: str,
        json_body: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        try:
            return await super()._post_json(url, json_body=json_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"東南旅遊請求逾時 ({self.timeout_seconds}s)，可能遭 WAF/Tarpit 阻塞: {url}"
            ) from exc

    def _build_payload(self, keyword: str = "", page_index: int = 1) -> Dict[str, Any]:
        start_date, end_date = self.get_default_query_date_range()
        return {
            "keyword": keyword,
            "beginDate": start_date,
            "endDate": end_date,
            "days": self.get_max_days(),
            "page": page_index,
            "pageSize": 20,
        }

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        all_items: List[TourListItem] = []
        seen_keys: set[tuple[str, str]] = set()
        headers = {
            "Origin": "https://trip.settour.com.tw",
            "Referer": "https://trip.settour.com.tw/search",
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
            payload.get("prodList")
            or payload.get("data", {}).get("prodList")
            or payload.get("result")
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
                row.get("prodNo") or row.get("ProdNo") or row.get("grupCd") or ""
            ).strip()
            tour_name = str(
                row.get("prodNm") or row.get("ProdName") or row.get("title") or ""
            ).strip()
            dep_date = self.normalize_date(
                row.get("begDt") or row.get("departDate") or row.get("GoDate")
            )
            days = self.parse_int_safe(row.get("prodDays") or row.get("days")) or 0

            if not (tour_code and tour_name and dep_date) or days < min_days or days > max_days:
                continue

            adult_price = self.parse_int_safe(
                row.get("b2cAmt") or row.get("price") or row.get("adultPrice")
            )
            seats = self.parse_int_safe(
                row.get("availQty") or row.get("remainQty") or row.get("seats")
            )
            status = str(row.get("statusNm") or row.get("status") or "未知").strip()
            if seats is not None and seats == 0 and status == "未知":
                status = "滿團"
            elif seats is not None and seats > 0 and status == "未知":
                status = "可報名"

            detail_url = str(row.get("prodUrl") or row.get("detailUrl") or "").strip()
            if not detail_url:
                detail_url = f"https://trip.settour.com.tw/travel/GFG/{tour_code}"
            elif detail_url.startswith("/"):
                detail_url = f"https://trip.settour.com.tw{detail_url}"

            airport = self.normalize_airport(
                row.get("departAirport") or row.get("beginCity"),
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
