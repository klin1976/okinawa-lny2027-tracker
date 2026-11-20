from __future__ import annotations
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from src.discovery.base_adapter import BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem

logger = logging.getLogger(__name__)


class RichmontAdapter(BaseAgencyAdapter):
    """山富旅遊清單撈取 Adapter（支援 /group/search/ SSR HTML 與 DOM 卡片解析）。"""

    agency_key = "richmont"
    agency_name = "山富旅遊"

    SEARCH_ENDPOINT = "https://www.travel4u.com.tw/group/search/"

    def _build_search_params(self, page_index: int = 1) -> Dict[str, Any]:
        date_range = self.common_filters.get("departure_date_range", {})
        return {
            "keyword": "沖繩",
            "date_start": date_range.get("start", "2027-02-01"),
            "date_end": date_range.get("end", "2027-02-14"),
            "length_end": self.common_filters.get("max_days", 5),
            "dep_location": "",
            "guarantee_depart": "False",
            "page": page_index,
        }

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        """Mode A: 直接以 httpx.AsyncClient GET 山富旅遊 SSR 搜尋頁並解析 DOM。"""
        all_items: List[TourListItem] = []
        seen_keys: set[tuple[str, str]] = set()
        search_url = self.search_url or self.SEARCH_ENDPOINT
        headers = {
            **self._default_headers(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.travel4u.com.tw/group/",
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

                if new_count == 0 or not re.search(rf"[?&]page={page_idx + 1}\b", resp.text):
                    break
                await self.jitter_sleep()

        return all_items

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
                row.get("tourCode") or row.get("grupCd") or row.get("id") or ""
            ).strip()
            tour_name = str(
                row.get("tourName") or row.get("name") or row.get("title") or ""
            ).strip()
            dep_date = self.normalize_date(row.get("departDate") or row.get("goDate"))
            days = self.parse_int_safe(row.get("days") or row.get("tourDays")) or 0

            if not (tour_code and tour_name and dep_date) or days > 5 or days < 1:
                continue

            adult_price = self.parse_int_safe(row.get("price") or row.get("adultPrice"))
            seats = self.parse_int_safe(row.get("seats") or row.get("availableSeats"))
            status = str(row.get("status") or "未知").strip()
            if seats is not None and seats == 0 and status == "未知":
                status = "滿團"
            elif seats is not None and seats > 0 and status == "未知":
                status = "可報名"

            detail_url = str(row.get("url") or row.get("detailUrl") or "").strip()
            if not detail_url:
                detail_url = f"https://www.travel4u.com.tw/group/itinerary/{tour_code}"
            elif detail_url.startswith("/"):
                detail_url = f"https://www.travel4u.com.tw{detail_url}"

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

    def _parse_departure_date(self, date_text: str, tour_code: str) -> Optional[str]:
        normalized = self.normalize_date(date_text)
        if normalized:
            return normalized
        m = re.search(r"(\d{1,2})[/-](\d{1,2})", date_text)
        if not m:
            return None
        mm = int(m.group(1))
        dd = int(m.group(2))
        mmdd = f"{mm:02d}{dd:02d}"
        m_yr = re.search(rf"(\d{{2}}){mmdd}", tour_code)
        if m_yr:
            year = f"20{m_yr.group(1)}"
        else:
            start_str = str(self.common_filters.get("departure_date_range", {}).get("start", "2027-02-01"))
            year = start_str[:4] if len(start_str) >= 4 and start_str[:4].isdigit() else "2027"
        return f"{year}-{mm:02d}-{dd:02d}"

    @staticmethod
    def _parse_richmont_status(small_text: str, seats: Optional[int]) -> str:
        if "保證出團" in small_text:
            return "保證出團"
        if "滿團" in small_text or "額滿" in small_text:
            return "滿團"
        if "候補" in small_text:
            return "候補"
        if "可報名" in small_text:
            return "可報名"
        if seats is not None:
            return "可報名" if seats > 0 else "滿團"
        return "未知"

    def parse_dom_fallback(self, html: str) -> List[TourListItem]:
        """從山富旅遊列表卡片 DOM 解析行程清單（對應 /group/search/ 實測選擇器）。"""
        soup = BeautifulSoup(html, "html.parser")
        results: List[TourListItem] = []

        for card in soup.select("div.products-grid div.product div.cardBox"):
            title_el = card.select_one("h6.tourCard.name")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not title:
                continue

            info_text = " ".join(el.get_text(" ", strip=True) for el in card.select("div.tour-info"))
            days_text = ""
            airport_text = ""
            for info_el in card.select("div.tour-info"):
                if info_el.select_one("i.fa-clock"):
                    days_text = info_el.get_text(" ", strip=True)
                if info_el.select_one("i.fa-location-arrow"):
                    airport_text = info_el.get_text(" ", strip=True)

            days_match = re.search(r"(\d+)\s*[天日]", days_text or info_text or title)
            days = int(days_match.group(1)) if days_match else 0
            if days > 5 or days < 1:
                continue

            price_el = card.select_one("div.price-deposit-h span.price")
            adult_price = self.parse_int_safe(price_el.get_text() if price_el else None)
            airport = self.normalize_airport(airport_text or info_text, title)

            for link_el in card.select('div.item.inline-block > a[href*="/group/product/"]'):
                href = (link_el.get("href") or "").strip()
                if not href:
                    continue
                m_code = re.search(r"/group/product/([^/?#]+)", href)
                code = m_code.group(1).strip() if m_code else ""
                if not code:
                    continue

                h6_el = link_el.select_one("h6")
                date_raw = h6_el.get_text(" ", strip=True) if h6_el else ""
                dep_date = self._parse_departure_date(date_raw, code)
                if not dep_date:
                    continue

                small_el = link_el.select_one("small")
                small_text = small_el.get_text(" ", strip=True) if small_el else ""
                seats_match = re.search(r"可售[:：\s]*(\d+)", small_text)
                seats = int(seats_match.group(1)) if seats_match else self.parse_int_safe(small_text)
                status = self._parse_richmont_status(small_text, seats)

                detail_url = (
                    f"https://www.travel4u.com.tw{href}" if href.startswith("/") else href
                )
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
