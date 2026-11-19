from __future__ import annotations
import asyncio
import json
import logging
import re
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from fast_flights import FlightQuery, Passengers, create_query, get_flights

from src.db.repository import TourRepository

logger = logging.getLogger(__name__)


@dataclass
class FlightBenchmarkResult:
    origin: str
    destination: str
    depart_date: str
    return_date: str
    min_price_twd: Optional[int]
    median_price_twd: Optional[int]
    flight_count: int
    sample_flights: List[Dict[str, Any]]
    error: Optional[str] = None

    def to_raw_json(self) -> str:
        return json.dumps(
            {
                "flight_count": self.flight_count,
                "sample_flights": self.sample_flights,
                "error": self.error,
            },
            ensure_ascii=False,
        )


def parse_price_twd(price_val: Any) -> Optional[int]:
    """將 fast-flights 回傳的價格（int 或如 'NT$12,450' 字串）轉為整數台幣。"""
    if price_val is None:
        return None
    if isinstance(price_val, (int, float)):
        val = int(price_val)
        return val if val > 0 else None
    digits = re.sub(r"[^\d]", "", str(price_val))
    if not digits:
        return None
    val = int(digits)
    return val if val > 0 else None


class FlightBenchmarkClient:
    """封裝 fast-flights 3.x 查詢台灣主要機場（TPE / KHH）往返沖繩（OKA）直飛機票基準價。"""

    def __init__(self, repository: Optional[TourRepository] = None):
        self.repository = repository

    def query_sync(
        self,
        origin: Literal["TPE", "KHH", "RMQ", "TSA"],
        destination: str = "OKA",
        depart_date: str = "2027-02-04",
        return_date: str = "2027-02-08",
        adults: int = 1,
        max_stops: int = 0,
        currency: str = "TWD",
        language: str = "zh-TW",
    ) -> FlightBenchmarkResult:
        """同步呼叫 fast-flights 查詢指定航段價格。"""
        query = create_query(
            flights=[
                FlightQuery(
                    date=depart_date,
                    from_airport=origin,
                    to_airport=destination,
                    max_stops=max_stops,
                ),
                FlightQuery(
                    date=return_date,
                    from_airport=destination,
                    to_airport=origin,
                    max_stops=max_stops,
                ),
            ],
            trip="round-trip",
            seat="economy",
            passengers=Passengers(adults=adults),
            currency=currency,
            language=language,
            max_stops=max_stops,
        )

        try:
            flights = get_flights(query)
        except Exception as exc:
            logger.warning(
                "fast-flights 查詢 %s->%s (%s~%s) 失敗: %s",
                origin,
                destination,
                depart_date,
                return_date,
                exc,
            )
            return FlightBenchmarkResult(
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                return_date=return_date,
                min_price_twd=None,
                median_price_twd=None,
                flight_count=0,
                sample_flights=[],
                error=str(exc),
            )

        flight_list = list(flights) if flights else []
        prices: List[int] = []
        samples: List[Dict[str, Any]] = []

        for f in flight_list:
            price_twd = parse_price_twd(getattr(f, "price", None))
            if price_twd is not None:
                prices.append(price_twd)
            if len(samples) < 10:
                legs = getattr(f, "flights", None) or []
                first_leg = legs[0] if legs else None
                samples.append(
                    {
                        "type": getattr(f, "type", None),
                        "airlines": getattr(f, "airlines", None),
                        "price_twd": price_twd,
                        "legs_count": len(legs),
                        "first_leg_departure": (
                            str(getattr(first_leg, "departure", None)) if first_leg else None
                        ),
                        "first_leg_arrival": (
                            str(getattr(first_leg, "arrival", None)) if first_leg else None
                        ),
                        "first_leg_duration": (
                            getattr(first_leg, "duration", None) if first_leg else None
                        ),
                    }
                )

        min_price = min(prices) if prices else None
        median_price = int(statistics.median(prices)) if prices else None

        return FlightBenchmarkResult(
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            return_date=return_date,
            min_price_twd=min_price,
            median_price_twd=median_price,
            flight_count=len(flight_list),
            sample_flights=samples,
        )

    async def fetch_and_save(
        self,
        origin: Literal["TPE", "KHH", "RMQ", "TSA"],
        destination: str = "OKA",
        depart_date: str = "2027-02-04",
        return_date: str = "2027-02-08",
        adults: int = 1,
        max_stops: int = 0,
    ) -> FlightBenchmarkResult:
        """非同步查詢機票基準並存入 SQLite flight_benchmarks（若有配置 repository）。"""
        result = await asyncio.to_thread(
            self.query_sync,
            origin,
            destination,
            depart_date,
            return_date,
            adults,
            max_stops,
        )
        if self.repository is not None and result.min_price_twd is not None:
            await self.repository.insert_flight_benchmark(
                origin=result.origin,
                destination=result.destination,
                depart_date=result.depart_date,
                return_date=result.return_date,
                min_price_twd=result.min_price_twd,
                median_price_twd=result.median_price_twd or result.min_price_twd,
                raw_json=result.to_raw_json(),
            )
        return result

    async def fetch_all_taiwan_oka_benchmarks(
        self,
        depart_date: str = "2027-02-04",
        return_date: str = "2027-02-08",
        origins: Optional[List[Literal["TPE", "KHH"]]] = None,
    ) -> Dict[str, FlightBenchmarkResult]:
        """同時查詢 TPE -> OKA 與 KHH -> OKA 基準價。"""
        target_origins: List[Literal["TPE", "KHH"]] = origins or ["TPE", "KHH"]
        results: Dict[str, FlightBenchmarkResult] = {}
        for org in target_origins:
            results[org] = await self.fetch_and_save(
                origin=org,
                destination="OKA",
                depart_date=depart_date,
                return_date=return_date,
            )
        return results
