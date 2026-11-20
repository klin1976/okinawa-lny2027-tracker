from __future__ import annotations
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from src.discovery.base_adapter import BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem

logger = logging.getLogger(__name__)


class FourPAdapter(BaseAgencyAdapter):
    """世邦旅遊清單撈取 Adapter（支援 /Products/Group/Search SSR HTML 與 DOM 解析）。"""

    agency_key = "fourp"
    agency_name = "世邦旅遊"

    SEARCH_ENDPOINT = "https://www.4p.com.tw/Products/Group/Search"

    def _build_search_params(self, page_index: int = 1) -> Dict[str, Any]:
        date_range = self.common_filters.get("departure_date_range", {})
        return {
            "kwd": "沖繩",
            "sdate": date_range.get("start", "2027-02-01"),
            "edate": date_range.get("end", "2027-02-14"),
            "page": page_index,
        }

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        """Mode A: 直接以 httpx.AsyncClient GET 世邦旅遊 SSR 搜尋頁並解析 DOM。"""
        all_items: List[TourListItem] = []
        seen_keys: set[tuple[str, str]] = set()
        search_url = self.search_url or self.SEARCH_ENDPOINT
        headers = {
            **self._default_headers(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.4p.com.tw/",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            for page_idx in range(1, 11):
                resp = await client.get(
                    search_url,
                    params=self._build_search_params(page_idx),
                    headers=headers,
                )
                resp.raise_for_status()
                items = self.parse_dom_fallback(resp.text)
                if not items:
                    break

                new_count = 0
                for item in items:
                    key = (item.tour_code, item.departure_date)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_items.append(item)
                        new_count += 1

                if new_count == 0 or not self._has_next_page(resp.text, page_idx + 1):
                    break
                await self.jitter_sleep()

        return all_items

    @staticmethod
    def _has_next_page(html: str, next_page: int) -> bool:
        return bool(
            re.search(rf"getPage\(['\"]?{next_page}['\"]?\)", html)
            or re.search(rf"[?&]page={next_page}\b", html)
        )

    def parse_xhr_payload(self, payload: Any) -> List[TourListItem]:
        if not isinstance(payload, dict):
            return []

        raw_list = (
            payload.get("tours")
            or payload.get("data")
            or payload.get("list")
            or payload.get("items")
            or []
        )
        if not isinstance(raw_list, list):
            return []

        results: List[TourListItem] = []
        for row in raw_list:
            if not isinstance(row, dict):
                continue
            tour_code = str(
                row.get("tourCode") or row.get("code") or row.get("id") or ""
            ).strip()
            tour_name = str(
                row.get("tourName") or row.get("name") or row.get("title") or ""
            ).strip()
            dep_date = self.normalize_date(row.get("departDate") or row.get("date"))
            days = self.parse_int_safe(row.get("days")) or 0

            if not (tour_code and tour_name and dep_date) or days > 5 or days < 1:
                continue

            adult_price = self.parse_int_safe(row.get("price") or row.get("adultPrice"))
            seats = self.parse_int_safe(row.get("seats") or row.get("vacancy"))
            status = str(row.get("status") or "未知").strip()
            if seats is not None and seats == 0 and status == "未知":
                status = "滿團"
            elif seats is not None and seats > 0 and status == "未知":
                status = "可報名"

            detail_url = str(row.get("url") or row.get("detailUrl") or "").strip()
            if not detail_url:
                detail_url = f"https://www.4p.com.tw/tour/{tour_code}"
            elif detail_url.startswith("/"):
                detail_url = f"https://www.4p.com.tw{detail_url}"

            airport = self.normalize_airport(row.get("airport"), tour_name)
            raw_hash = self.compute_raw_hash(
                self.agency_name, tour_code, dep_date, adult_price, seats, status
            )
            results.append(
                TourListItem(
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

    @staticmethod
    def _parse_fourp_status(tag_text: str, btn_text: str, seats: Optional[int]) -> str:
        combined = f"{tag_text} {btn_text}"
        if "保證出團" in combined or "保證出發" in combined:
            return "保證出團"
        if "滿團" in combined or "額滿" in combined:
            return "滿團"
        if "候補" in combined:
            return "候補"
        if "報名" in combined:
            return "可報名"
        if seats is not None:
            return "可報名" if seats > 0 else "滿團"
        return "未知"

    def parse_dom_fallback(self, html: str) -> List[TourListItem]:
        """從世邦旅遊伺服器渲染 HTML 列表抽取行程資訊（對應 /Products/Group/Search 實測選擇器）。"""
        soup = BeautifulSoup(html, "html.parser")
        results: List[TourListItem] = []

        for card in soup.select("#search-block figure.block_style"):
            link_el = card.select_one('a[href*="/products/group/detail"]')
            href = (link_el.get("href") or "").strip() if link_el else ""

            code_el = card.select_one(".go_number h6")
            code = code_el.get_text(strip=True) if code_el else ""
            if not code and href:
                qs = parse_qs(urlparse(href).query)
                code = (qs.get("id") or [""])[0].strip()
            if not code:
                plane_el = card.select_one(".plane[data-id]")
                code = (plane_el.get("data-id") or "").strip() if plane_el else ""

            title_el = card.select_one(".main_words a h4")
            title = title_el.get_text(" ", strip=True) if title_el else ""

            date_el = card.select_one(".go-date")
            dep_date = self.normalize_date(date_el.get_text(" ", strip=True) if date_el else None)

            days_el = card.select_one(".item_days")
            days_text = days_el.get_text(" ", strip=True) if days_el else ""
            days_match = re.search(r"(\d+)", days_text) or re.search(r"(\d+)\s*[天日]", title)
            days = int(days_match.group(1)) if days_match else 0

            if not (code and title and dep_date) or days > 5 or days < 1:
                continue

            airport_el = card.select_one(".go-airport .airport")
            airport_text = airport_el.get_text(" ", strip=True) if airport_el else None
            airport = self.normalize_airport(airport_text, title)

            price_el = card.select_one(".price_box span.text-danger")
            adult_price = self.parse_int_safe(price_el.get_text() if price_el else None)

            seats_el = card.select_one(".available span.text-danger")
            seats = self.parse_int_safe(seats_el.get_text() if seats_el else None)

            tag_text = " ".join(
                el.get_text(" ", strip=True) for el in card.select(".go_tag a.tag:not(.d-none)")
            )
            btn_el = card.select_one("a.btn-primary")
            btn_text = btn_el.get_text(" ", strip=True) if btn_el else ""
            status = self._parse_fourp_status(tag_text, btn_text, seats)

            detail_url = (
                f"https://www.4p.com.tw{href}" if href.startswith("/") else href
            ) or f"https://www.4p.com.tw/products/group/detail?id={code}"

            raw_hash = self.compute_raw_hash(
                self.agency_name, code, dep_date, adult_price, seats, status
            )
            results.append(
                TourListItem(
                    agency=self.agency_name,
                    tour_code=code,
                    tour_name=title,
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
