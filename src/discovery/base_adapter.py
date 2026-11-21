from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import httpx
from playwright.async_api import async_playwright

from src.schemas.discovery_schema import TourListItem

if TYPE_CHECKING:
    from src.schemas.trip_schema import TripConfig

logger = logging.getLogger(__name__)


class AgencyFetchError(RuntimeError):
    """單一旅行社可用模式皆抓取失敗時拋出。"""


class BaseAgencyAdapter(ABC):
    """五大旅行社上游清單自動撈取抽象基底類別（支援 Mode A Direct XHR/SSR + Mode B Playwright 備援）。"""

    agency_key: str = ""
    agency_name: str = ""

    def __init__(
        self,
        agency_config: Optional[Dict[str, Any]] = None,
        common_filters: Optional[Dict[str, Any]] = None,
        concurrency_config: Optional[Dict[str, Any]] = None,
        trip_config: Optional["TripConfig"] = None,
        allow_playwright_fallback: bool = True,
    ):
        self.agency_config = agency_config or {}
        self.trip_config = trip_config
        self.allow_playwright_fallback = allow_playwright_fallback

        merged_filters = dict(common_filters or {})
        if trip_config is not None:
            trip_filters = trip_config.to_common_filters()
            for k, v in trip_filters.items():
                merged_filters.setdefault(k, v)
            # 若傳入 TripConfig，以 TripConfig 專案設定覆寫目的地與日期限制
            merged_filters.update(trip_filters)

        self.common_filters: Dict[str, Any] = merged_filters
        self.trip_id: str = (
            trip_config.trip_id
            if trip_config is not None
            else str(self.common_filters.get("trip_id") or "default")
        )
        self.concurrency_config = concurrency_config or {}

        self.search_url: str = self.agency_config.get("search_url", "")
        self.api_pattern: str = self.agency_config.get("api_pattern", "")
        self.timeout_seconds: float = float(self.agency_config.get("timeout_seconds", 30))
        self.jitter_min: float = float(self.concurrency_config.get("jitter_min_seconds", 2.0))
        self.jitter_max: float = float(self.concurrency_config.get("jitter_max_seconds", 4.5))

    def get_search_keywords(self) -> List[str]:
        raw = self.common_filters.get("destination_keywords") or []
        return [str(k).strip() for k in raw if str(k).strip()]

    def get_exclude_keywords(self) -> List[str]:
        raw = self.common_filters.get("exclude_keywords") or []
        return [str(k).strip() for k in raw if str(k).strip()]

    def get_date_range(self) -> Tuple[str, str]:
        date_range = self.common_filters.get("departure_date_range") or {}
        start = str(date_range.get("start") or "").strip()
        end = str(date_range.get("end") or "").strip()
        return start, end

    def get_default_query_date_range(self) -> Tuple[str, str]:
        start, end = self.get_date_range()
        if not start:
            start = datetime.now().strftime("%Y-%m-%d")
        if not end:
            end = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        return start, end

    def get_min_days(self) -> int:
        return max(1, int(self.common_filters.get("min_days", 1)))

    def get_max_days(self) -> int:
        return min(30, int(self.common_filters.get("max_days", 30)))

    @staticmethod
    def compute_raw_hash(
        agency: str,
        tour_code: str,
        departure_date: str,
        adult_price: Optional[int],
        seats_available: Optional[int],
        status: str,
    ) -> str:
        payload = f"{agency}|{tour_code}|{departure_date}|{adult_price}|{seats_available}|{status}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def normalize_airport(raw_airport: Optional[str], tour_name: str = "") -> str:
        text = f"{raw_airport or ''} {tour_name}".upper()
        if "TPE" in text or "桃園" in text or "台北" in text:
            return "TPE"
        if "KHH" in text or "高雄" in text or "小港" in text:
            return "KHH"
        if "RMQ" in text or "台中" in text or "清泉崗" in text:
            return "RMQ"
        if "TSA" in text or "松山" in text:
            return "TSA"
        return "OTHER"

    @staticmethod
    def parse_int_safe(val: Any) -> Optional[int]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return int(val)
        digits = re.sub(r"[^\d]", "", str(val))
        return int(digits) if digits else None

    @staticmethod
    def normalize_date(raw_date: Any) -> Optional[str]:
        if not raw_date:
            return None
        text = str(raw_date).strip()
        m = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
        if not m:
            return None
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    async def jitter_sleep(self) -> None:
        delay = random.uniform(self.jitter_min, self.jitter_max)
        await asyncio.sleep(delay)

    def apply_common_filters(self, items: List[TourListItem]) -> List[TourListItem]:
        """依據 TripConfig 或 common_filters 過濾天數區間、出發日期、關鍵字與排除字詞。"""
        min_days = self.get_min_days()
        max_days = self.get_max_days()
        start_str, end_str = self.get_date_range()
        keywords = self.get_search_keywords()
        exclude_keywords = self.get_exclude_keywords()

        filtered: List[TourListItem] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            if item.days < min_days or item.days > max_days:
                continue
            if start_str and item.departure_date < start_str:
                continue
            if end_str and item.departure_date > end_str:
                continue
            title_lower = item.tour_name.lower()
            if keywords and not any(kw.lower() in title_lower for kw in keywords):
                continue
            if exclude_keywords and any(ex.lower() in title_lower for ex in exclude_keywords):
                continue

            dedup_key = (item.tour_code, item.departure_date)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            item.trip_id = self.trip_id
            filtered.append(item)
        return filtered

    async def fetch_tours(self) -> Tuple[List[TourListItem], str]:
        """
        雙模式自動容錯執行清單撈取：
        優先嘗試 Mode A (Direct XHR/SSR)，若失敗且允許降級則自動切換至 Mode B (Playwright Interception)。
        回傳: (過濾後的 TourListItem 清單, 實際採用的模式 'mode_a_xhr' | 'mode_b_playwright')
        """
        mode_a_error: Optional[Exception] = None
        try:
            items = await self.fetch_mode_a_xhr()
            if items is not None:
                return self.apply_common_filters(items), "mode_a_xhr"
        except Exception as exc:
            mode_a_error = exc
            if not self.allow_playwright_fallback:
                raise AgencyFetchError(
                    f"[{self.agency_name}] Mode A 失敗且已停用 Playwright 降級 (--no-playwright): {exc}"
                ) from exc
            logger.warning(
                "[%s] Mode A (Direct XHR/SSR) 失敗，降級切換至 Mode B (Playwright): %s",
                self.agency_name,
                exc,
            )

        if not self.allow_playwright_fallback:
            raise AgencyFetchError(
                f"[{self.agency_name}] Mode A 無結果且已停用 Playwright 降級 (--no-playwright)"
            )

        try:
            items = await self.fetch_mode_b_playwright()
            return self.apply_common_filters(items), "mode_b_playwright"
        except Exception as exc:
            raise AgencyFetchError(
                f"[{self.agency_name}] 雙模式皆失敗 | Mode A: {mode_a_error} | Mode B: {exc}"
            ) from exc

    @abstractmethod
    async def fetch_mode_a_xhr(self) -> List[TourListItem]:
        """Mode A: 使用 httpx.AsyncClient 直接呼叫旅行社搜尋 XHR API 或 SSR HTML。"""

    async def fetch_mode_b_playwright(self) -> List[TourListItem]:
        """
        Mode B: 使用無頭 Chromium 開啟搜尋頁並攔截符合 api_pattern 的 JSON XHR 回應；
        若無對應 XHR，子類別可覆寫 parse_dom_fallback 從 HTML DOM 抽取。
        """
        captured_items: List[TourListItem] = []
        pattern_re = re.compile(self.api_pattern, re.IGNORECASE) if self.api_pattern else None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="zh-TW",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            async def handle_response(response):
                try:
                    if pattern_re and not pattern_re.search(response.url):
                        return
                    ctype = (response.headers.get("content-type") or "").lower()
                    if "json" not in ctype:
                        return
                    payload = await response.json()
                    parsed = self.parse_xhr_payload(payload)
                    captured_items.extend(parsed)
                except Exception as exc:
                    logger.debug("[%s] Playwright XHR 解析略過 (%s): %s", self.agency_name, response.url, exc)

            page.on("response", handle_response)
            await page.goto(
                self.search_url,
                wait_until="domcontentloaded",
                timeout=int(self.timeout_seconds * 1000),
            )
            await self.jitter_sleep()

            if not captured_items:
                html = await page.content()
                captured_items.extend(self.parse_dom_fallback(html))

            await browser.close()

        return captured_items

    @abstractmethod
    def parse_xhr_payload(self, payload: Any) -> List[TourListItem]:
        """將旅行社 XHR JSON 回應解析並正規化為 TourListItem 陣列。"""

    def parse_dom_fallback(self, html: str) -> List[TourListItem]:
        """伺服器渲染網頁（無 JSON XHR）之 HTML DOM 備援解析器，預設回傳空陣列。"""
        return []

    def _default_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        }

    async def _post_json(self, url: str, json_body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Any:
        merged = {**self._default_headers(), **(headers or {})}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            resp = await client.post(url, json=json_body, headers=merged)
            resp.raise_for_status()
            return resp.json()
