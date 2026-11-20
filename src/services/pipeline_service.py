from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.calculator.alert_detector import AlertDetector
from src.calculator.budget_engine import BudgetEngine
from src.config import Settings, get_settings, load_agencies_config, load_family_profile
from src.db.database import init_db
from src.db.repository import TourRepository
from src.discovery import build_enabled_adapters
from src.discovery.base_adapter import BaseAgencyAdapter
from src.extractor.detail_crawler import DetailCrawler
from src.extractor.flight_benchmark import FlightBenchmarkClient
from src.schemas.budget_schema import AlertEvent, RankedTourResult
from src.schemas.discovery_schema import TourListItem
from src.schemas.tour_schema import OkinawaTourPackage, PricingDetail

logger = logging.getLogger(__name__)


class PipelineService:
    """串聯 Module 1 (清單抓取) -> SQLite 增量比對 -> Module 2 (詳情與機票) -> Module 3 (試算與告警)。"""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        repository: Optional[TourRepository] = None,
        detail_crawler: Optional[DetailCrawler] = None,
        flight_client: Optional[FlightBenchmarkClient] = None,
        budget_engine: Optional[BudgetEngine] = None,
        alert_detector: Optional[AlertDetector] = None,
        adapters: Optional[List[BaseAgencyAdapter]] = None,
    ):
        self.settings = settings or get_settings()
        self.repo = repository or TourRepository(self.settings.database_path)
        self.detail_crawler = detail_crawler or DetailCrawler(self.settings)
        self.flight_client = flight_client or FlightBenchmarkClient(self.repo)

        family_profile = load_family_profile("config/family_profile.yaml")
        self.budget_engine = budget_engine or BudgetEngine(family_profile)
        self.alert_detector = alert_detector or AlertDetector(family_profile)
        self._custom_adapters = adapters

    @staticmethod
    def _needs_detail_parse(tour_row: Optional[Dict[str, Any]], force_reparse: bool = False, max_age_days: int = 7) -> bool:
        if force_reparse or not tour_row:
            return True
        parsed_at_str = tour_row.get("detail_parsed_at")
        if not parsed_at_str or not tour_row.get("detail_json"):
            return True
        try:
            parsed_at = datetime.fromisoformat(parsed_at_str)
            if parsed_at.tzinfo is None:
                parsed_at = parsed_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - parsed_at
            return age > timedelta(days=max_age_days)
        except Exception:
            return True

    @staticmethod
    def _build_package_from_list_fallback(item: TourListItem) -> OkinawaTourPackage:
        """當詳情頁尚未解析（受限單次上限或失敗）時，以清單欄位建立最小可用模型供試算。"""
        return OkinawaTourPackage(
            agency=item.agency,
            tour_code=item.tour_code,
            tour_name=item.tour_name,
            source_url=item.detail_url,
            days=item.days,
            nights=max(0, item.days - 1),
            departure_date=item.departure_date,
            departure_airport=item.departure_airport if item.departure_airport in {"TPE", "KHH", "RMQ", "TSA", "OTHER"} else "OTHER",
            status=item.status if item.status in {"可報名", "保證出團", "候補", "滿團", "已截止", "未知"} else "未知",
            seats_available=item.seats_available,
            pricing=PricingDetail(adult_twin_price=item.adult_price),
        )

    async def run_daily_pipeline(
        self,
        agencies: Optional[List[str]] = None,
        force_reparse: bool = False,
        max_new_details_per_run: Optional[int] = None,
        skip_flight_benchmark: bool = False,
    ) -> Dict[str, Any]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        await init_db(self.repo.db_path)

        detail_limit = (
            max_new_details_per_run
            if max_new_details_per_run is not None
            else self.settings.max_new_details_per_run
        )

        if self._custom_adapters is not None:
            adapters = self._custom_adapters
        else:
            agencies_cfg = load_agencies_config("config/agencies.yaml")
            adapters = build_enabled_adapters(agencies_cfg, target_keys=agencies)

        discovered_items: List[TourListItem] = []
        agency_stats: Dict[str, Any] = {}
        errors: List[Dict[str, str]] = []
        alerts: List[AlertEvent] = []

        # 1. 模組一：依序執行各旅行社抓取（併發=1，單社失敗不中斷整體）
        for adapter in adapters:
            try:
                items, mode_used = await adapter.fetch_tours()
                discovered_items.extend(items)
                agency_stats[adapter.agency_name] = {
                    "count": len(items),
                    "mode": mode_used,
                    "status": "OK",
                }
            except Exception as exc:
                err_msg = str(exc)
                logger.error("旅行社抓取失敗 [%s]: %s", adapter.agency_name, err_msg)
                errors.append({"agency": adapter.agency_name, "error": err_msg})
                agency_stats[adapter.agency_name] = {
                    "count": 0,
                    "mode": "FAILED",
                    "status": "ERROR",
                }
                err_alert_key = f"AGENCY_CRAWL_ERROR:{adapter.agency_key}:{run_id[:8]}"
                if not await self.repo.is_alert_logged(err_alert_key):
                    err_alert = AlertEvent(
                        alert_key=err_alert_key,
                        alert_type="AGENCY_CRAWL_ERROR",
                        tour_uid=None,
                        priority="維運",
                        message=f"旅行社 [{adapter.agency_name}] 雙模式抓取失敗，請檢查 XHR 參數：{err_msg[:180]}",
                        details={"agency": adapter.agency_name, "error": err_msg},
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                    alerts.append(err_alert)
                    await self.repo.insert_alert_log(
                        err_alert.alert_key, err_alert.alert_type, None, err_alert.message
                    )

        # 2. 機票基準查詢（TPE/KHH <-> OKA）
        flight_min_by_airport: Dict[str, int] = {}
        if not skip_flight_benchmark:
            try:
                bm_results = await self.flight_client.fetch_all_taiwan_oka_benchmarks()
                for origin, bm in bm_results.items():
                    if bm.min_price_twd is not None:
                        flight_min_by_airport[origin] = bm.min_price_twd
            except Exception as exc:
                logger.warning("機票基準查詢略過: %s", exc)

        # 3. 增量比對 + 詳情解析 (Cost Control) + 家族試算 + 快照 & 告警
        llm_calls_used = 0
        llm_skipped_cached = 0
        ranked_results: List[RankedTourResult] = []
        snapshot_contexts: List[Dict[str, Any]] = []

        for item in discovered_items:
            tour_uid = await self.repo.upsert_tour_from_list(item)
            tour_row = await self.repo.get_tour(tour_uid)

            package: Optional[OkinawaTourPackage] = None
            if self._needs_detail_parse(tour_row, force_reparse=force_reparse, max_age_days=7):
                if llm_calls_used < detail_limit:
                    try:
                        package = await self.detail_crawler.parse_url(
                            url=item.detail_url, agency_hint=item.agency
                        )
                        await self.repo.update_tour_detail(tour_uid, package.model_dump_json())
                        llm_calls_used += 1
                    except Exception as exc:
                        logger.warning("詳情解析失敗 (%s): %s", tour_uid, exc)
                        errors.append({"tour_uid": tour_uid, "error": f"detail_parse: {exc}"})
            else:
                llm_skipped_cached += 1
                try:
                    package = OkinawaTourPackage.model_validate_json(tour_row["detail_json"])
                except Exception:
                    package = None

            if package is None:
                package = self._build_package_from_list_fallback(item)

            # 以模組一即時價格與剩餘機位覆寫靜態詳情（確保即時性）
            if item.adult_price is not None:
                package.pricing.adult_twin_price = item.adult_price
            if item.seats_available is not None:
                package.seats_available = item.seats_available
            if item.status in {"可報名", "保證出團", "候補", "滿團", "已截止", "未知"}:
                package.status = item.status

            bm_price = flight_min_by_airport.get(package.departure_airport)
            budget_res = self.budget_engine.calculate(package, benchmark_flight_min_price=bm_price)

            # 寫入當日快照
            await self.repo.insert_price_snapshot(
                tour_uid=tour_uid,
                adult_price=item.adult_price or package.pricing.adult_twin_price,
                seats_available=item.seats_available if item.seats_available is not None else package.seats_available,
                status=package.status,
                estimated_family_total=budget_res.grand_total_twd,
            )

            ranked_results.append(
                RankedTourResult(
                    tour_uid=tour_uid,
                    agency=item.agency,
                    tour_name=package.tour_name,
                    departure_date=item.departure_date,
                    days=item.days,
                    departure_airport=item.departure_airport,
                    adult_price=item.adult_price or package.pricing.adult_twin_price,
                    seats_available=package.seats_available,
                    detail_url=item.detail_url,
                    budget=budget_res,
                    composite_score=budget_res.composite_score,
                )
            )
            snapshot_contexts.append(
                {
                    "tour_uid": tour_uid,
                    "item": item,
                    "package": package,
                    "budget": budget_res,
                }
            )

        # 依綜合推薦分數排序，決定是否進入 Top 5
        ranked_results.sort(key=lambda r: r.composite_score, reverse=True)
        top_5_uids = {r.tour_uid for r in ranked_results[:5]}

        # 4. 偵測各團異動告警並寫入 alert_logs 去重
        for ctx in snapshot_contexts:
            uid = ctx["tour_uid"]
            snaps = await self.repo.get_latest_two_snapshots(uid)
            curr_snap = snaps[0] if len(snaps) >= 1 else {}
            prev_snap = snaps[1] if len(snaps) >= 2 else None

            detected = self.alert_detector.detect_alerts(
                tour_uid=uid,
                current_snapshot=curr_snap,
                prev_snapshot=prev_snap,
                budget_result=ctx["budget"],
                tour_package=ctx["package"],
                is_top_ranked=(uid in top_5_uids),
            )
            for ev in detected:
                if not await self.repo.is_alert_logged(ev.alert_key):
                    alerts.append(ev)
                    await self.repo.insert_alert_log(
                        ev.alert_key, ev.alert_type, ev.tour_uid, ev.message
                    )

        return {
            "run_id": run_id,
            "status": "PARTIAL_SUCCESS" if errors else "SUCCESS",
            "stats": {
                "total_discovered": len(discovered_items),
                "llm_calls_used": llm_calls_used,
                "llm_skipped_cached": llm_skipped_cached,
                "alerts_count": len(alerts),
                "agencies": agency_stats,
                "flight_benchmarks_twd": flight_min_by_airport,
            },
            "alerts": [a.model_dump() for a in alerts],
            "top_5_rankings": [r.model_dump() for r in ranked_results[:5]],
            "errors": errors,
        }
