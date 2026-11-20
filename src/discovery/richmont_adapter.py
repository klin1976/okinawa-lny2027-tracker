from __future__ import annotations
import logging
import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup

from src.discovery.base_adapter import BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem

logger = logging.getLogger(__name__)


class RichmontAdapter(BaseAgencyAdapter):
    """山富旅遊清單撈取 Adapter（支援 /group/ JSON 與 DOM 卡片備援）。"""

    agency_key = "richmont"
    agency_name = "山富旅遊"

    XHR_ENDPOINT = "https://www.travel4u.com.tw/group/api/search"

    def _build_payload(self, page_index: int = 1) -> Dict[str, Any]:
        date_range = self.common_filters.get("departure_date_range", {})
        return {
            "keyword": "沖繩",
            "startDate": date_range.get("start", "2027-02-01"),
            "endDate": date_range.get("end", "2027-02-14"),
            "maxDays": self.common_filters.get("max_days", 5),
            "page": page_index,
        }

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        all_items: List[TourListItem] = []
        headers = {
            "Origin": "https://www.travel4u.com.tw",
            "Referer": "https://www.travel4u.com.tw/group/",
        }
        for page_idx in range(1, 6):
            payload = await self._post_json(
                self.XHR_ENDPOINT,
                json_body=self._build_payload(page_idx),
                headers=headers,
            )
            items = self.parse_xhr_payload(payload)
            if not items:
                break
            all_items.extend(items)
            if len(items) < 20:
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

    def parse_dom_fallback(self, html: str) -> List[TourListItem]:
        """從山富旅遊列表卡片 DOM 解析行程清單。"""
        soup = BeautifulSoup(html, "html.parser")
        results: List[TourListItem] = []

        for card in soup.select("[data-tour-code], .tour-card, .group-item"):
            code = (card.get("data-tour-code") or "").strip()
            title_el = card.select_one("h2, h3, .tour-title, .title, a")
            title = title_el.get_text(strip=True) if title_el else ""
            link_el = card.select_one("a[href]")
            href = (link_el.get("href") or "").strip() if link_el else ""
            if not code and href:
                m_code = re.search(r"([A-Z0-9]{6,})", href)
                code = m_code.group(1) if m_code else ""

            text_blob = card.get_text(" ", strip=True)
            dep_date = self.normalize_date(card.get("data-depart-date") or text_blob)
            days_match = re.search(r"(\d+)\s*[天日]", title or text_blob)
            days = int(days_match.group(1)) if days_match else 0

            if not (code and title and dep_date) or days > 5 or days < 1:
                continue

            price_el = card.select_one(".price, .tour-price")
            adult_price = self.parse_int_safe(price_el.get_text() if price_el else None)
            seats_el = card.select_one(".seats, .vacancy")
            seats = self.parse_int_safe(seats_el.get_text() if seats_el else None)
            status = "可報名" if (seats or 0) > 0 else "未知"

            detail_url = (
                f"https://www.travel4u.com.tw{href}" if href.startswith("/") else href
            ) or f"https://www.travel4u.com.tw/group/itinerary/{code}"

            airport = self.normalize_airport(None, title)
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
