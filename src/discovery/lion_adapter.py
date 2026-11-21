from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.discovery.base_adapter import BaseAgencyAdapter
from src.schemas.discovery_schema import TourListItem

logger = logging.getLogger(__name__)


class LionAdapter(BaseAgencyAdapter):
    """雄獅旅遊清單撈取 Adapter（對齊 grouplistinfojson XHR 與 Playwright 備援）。"""

    agency_key = "lion"
    agency_name = "雄獅旅遊"

    XHR_ENDPOINT = "https://travel.liontravel.com/search/grouplistinfojson"

    def _build_payload(self, keyword: str = "", page_index: int = 1) -> Dict[str, Any]:
        start_date, end_date = self.get_default_query_date_range()
        return {
            "ArriveID": None,
            "GoDatestart": start_date,
            "GoDateEnd": end_date,
            "GroupID": None,
            "Keywords": keyword or None,
            "IsEnsureGroup": None,
            "IsSold": None,
            "ThemeID": None,
            "TravelPavilionGroupID": None,
            "KeywordsCity": None,
            "TravelType": 1,  # 1=團體旅遊
            "BuIDs": "",
            "PreferAirlines": None,
            "DepartureID": "",
            "WeekDay": "",
            "PriceList": None,
            "AirlineIDs": "",
            "TripTypes": "",
            "Tags": "",
            "SortType": 3,
            "Days": "",
            "MarketingProjects": "",
            "Page": page_index,
            "PageSize": 20,
        }

    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        all_items: List[TourListItem] = []
        seen_keys: set[tuple[str, str]] = set()
        headers = {
            "Origin": "https://travel.liontravel.com",
            "Referer": "https://travel.liontravel.com/search",
            "Content-Type": "application/json;charset=UTF-8",
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
                total_page = payload.get("TotalPage", 1) if isinstance(payload, dict) else 1
                if page_idx >= total_page:
                    break
                await self.jitter_sleep()
        return all_items

    def _build_item_from_fields(
        self,
        tour_code: str,
        tour_name: str,
        dep_date: str,
        days: int,
        adult_price: Any,
        seats: Any,
        status_raw: Any,
        is_guaranteed: bool,
        detail_url: str,
        airport_raw: Any,
    ) -> TourListItem:
        price_int = self.parse_int_safe(adult_price)
        seats_int = self.parse_int_safe(seats)
        raw_s = str(status_raw or "未知").strip()
        status_map = {
            "ensure": "保證出團",
            "guaranteed": "保證出團",
            "open": "可報名",
            "normal": "可報名",
            "wait": "候補",
            "full": "滿團",
            "soldout": "滿團",
        }
        status = status_map.get(raw_s.lower(), raw_s)
        if is_guaranteed or status == "保證出團":
            status = "保證出團"
        elif seats_int is not None and seats_int == 0 and status in {"未知", ""}:
            status = "滿團"
        elif seats_int is not None and seats_int > 0 and status in {"未知", ""}:
            status = "可報名"

        if not detail_url:
            detail_url = f"https://travel.liontravel.com/detail?NormGroupID={tour_code}"
        elif detail_url.startswith("/"):
            detail_url = f"https://travel.liontravel.com{detail_url}"

        airport = self.normalize_airport(str(airport_raw or ""), tour_name)
        raw_hash = self.compute_raw_hash(
            self.agency_name, tour_code, dep_date, price_int, seats_int, status
        )
        return TourListItem(
            trip_id=self.trip_id,
            agency=self.agency_name,
            tour_code=tour_code,
            tour_name=tour_name,
            departure_date=dep_date,
            days=days,
            departure_airport=airport,
            adult_price=price_int,
            seats_available=seats_int,
            status=status,
            detail_url=detail_url,
            raw_hash=raw_hash,
        )

    def parse_xhr_payload(self, payload: Any) -> List[TourListItem]:
        if not isinstance(payload, dict):
            return []

        raw_list = (
            payload.get("NormGroupList")
            or payload.get("Data", {}).get("NormGroupList")
            or payload.get("GroupList")
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

            norm_id = str(row.get("NormGroupID") or row.get("TourCode") or "").strip()
            tour_name = str(
                row.get("TourName") or row.get("NormGroupName") or row.get("Title") or ""
            ).strip()
            days = self.parse_int_safe(row.get("TourDays") or row.get("Days")) or 0
            if not tour_name or days < min_days or days > max_days:
                continue

            start_cities = row.get("StartFromCityList")
            if isinstance(start_cities, list) and start_cities:
                airport_hint = ",".join(
                    str(c.get("CityName", c)) if isinstance(c, dict) else str(c)
                    for c in start_cities
                )
            else:
                airport_hint = row.get("DepartureCity") or row.get("DepartureAirport")

            sub_groups = row.get("GroupList")
            if isinstance(sub_groups, list) and sub_groups:
                for sub in sub_groups:
                    if not isinstance(sub, dict):
                        continue
                    sub_code = str(sub.get("GroupID") or norm_id).strip()
                    dep_date = self.normalize_date(
                        sub.get("GoDate") or sub.get("StartDate") or sub.get("DepartureDate")
                    )
                    if not (sub_code and dep_date):
                        continue
                    sub_url = str(sub.get("Url") or sub.get("DetailUrl") or "").strip()
                    if not sub_url and norm_id:
                        sub_url = f"https://travel.liontravel.com/detail?NormGroupID={norm_id}&GroupID={sub_code}"
                    results.append(
                        self._build_item_from_fields(
                            tour_code=sub_code,
                            tour_name=tour_name,
                            dep_date=dep_date,
                            days=days,
                            adult_price=sub.get("Price") or sub.get("GroupStraightPrice") or row.get("GroupStraightPrice"),
                            seats=sub.get("AvailableVacancy") or sub.get("Vacancy") or sub.get("SeatsAvailable"),
                            status_raw=sub.get("Status") or sub.get("OrderStatus") or row.get("Status"),
                            is_guaranteed=bool(sub.get("IsEnsureGroup") or sub.get("IsGuaranteed") or row.get("IsGuaranteed")),
                            detail_url=sub_url,
                            airport_raw=airport_hint,
                        )
                    )
            else:
                dep_date = self.normalize_date(row.get("GoDate") or row.get("DepartureDate"))
                if not (norm_id and dep_date):
                    continue
                results.append(
                    self._build_item_from_fields(
                        tour_code=norm_id,
                        tour_name=tour_name,
                        dep_date=dep_date,
                        days=days,
                        adult_price=row.get("GroupStraightPrice") or row.get("Price") or row.get("AdultPrice"),
                        seats=row.get("AvailableVacancy") or row.get("SeatsAvailable"),
                        status_raw=row.get("OrderStatus") or row.get("Status"),
                        is_guaranteed=bool(row.get("IsGuaranteed")),
                        detail_url=str(row.get("DetailUrl") or row.get("Url") or "").strip(),
                        airport_raw=airport_hint,
                    )
                )
        return results
