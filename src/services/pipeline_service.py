from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.calculator.alert_detector import AlertDetector
from src.calculator.budget_engine import BudgetEngine
from src.config import (
    Settings,
    get_settings,
    load_agencies_config,
    load_family_profile,
    load_trip_config,
)
from src.db.database import init_db
from src.db.repository import TourRepository
from src.discovery import build_enabled_adapters
from src.discovery.base_adapter import BaseAgencyAdapter
from src.evaluator import DiffEngine, RuleEvaluator
from src.extractor.detail_crawler import DetailCrawler
from src.extractor.flight_benchmark import FlightBenchmarkClient
from src.schemas.budget_schema import AlertEvent, RankedTourResult
from src.schemas.discovery_schema import TourListItem
from src.schemas.tour_schema import PricingDetail, TourPackage
from src.schemas.trip_schema import TripConfig

logger = logging.getLogger(__name__)


class PipelineService:
    """串聯清單撈取 -> SQLite 增量比對與事件快照 -> 詳情/機票基準 -> 雙層試算評分與告警差異引擎。"""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        repository: Optional[TourRepository] = None,
        detail_crawler: Optional[DetailCrawler] = None,
        flight_client: Optional[FlightBenchmarkClient] = None,
        budget_engine: Optional[BudgetEngine] = None,
        alert_detector: Optional[AlertDetector] = None,
        adapters: Optional[List[BaseAgencyAdapter]] = None,
        trip_config: Optional[TripConfig] = None,
        allow_playwright_fallback: bool = True,
    ):
        self.settings = settings or get_settings()
        self.repo = repository or TourRepository(self.settings.database_path)
        self._using_default_crawler = detail_crawler is None
        self.detail_crawler = detail_crawler or DetailCrawler(self.settings)
        self.flight_client = flight_client or FlightBenchmarkClient(self.repo)
        self._custom_adapters = adapters
        self.allow_playwright_fallback = allow_playwright_fallback

        if trip_config is not None:
            self.trip_config: Optional[TripConfig] = trip_config
        else:
            self.trip_config = self._try_load_default_trip_config()

        if self.trip_config is not None:
            base_profile = self._load_base_profile(self.trip_config.party.family_profile_ref)
            effective_profile = self.trip_config.build_effective_profile(base_profile)
        else:
            effective_profile = self._load_base_profile("config/family_profile.yaml")

        self.budget_engine = budget_engine or BudgetEngine(effective_profile)
        self.alert_detector = alert_detector or AlertDetector(effective_profile)

    def _try_load_default_trip_config(self) -> Optional[TripConfig]:
        default_trip = Path(self.settings.trips_dir) / "okinawa_lny2027.yaml"
        if default_trip.exists():
            try:
                return load_trip_config(default_trip)
            except Exception as exc:
                logger.warning("載入預設旅遊專案設定失敗 (%s): %s", default_trip, exc)
        return None

    @staticmethod
    def _load_base_profile(path_str: Optional[str]) -> Dict[str, Any]:
        if path_str and Path(path_str).exists():
            return load_family_profile(path_str)
        if Path("config/family_profile.yaml").exists():
            return load_family_profile("config/family_profile.yaml")
        return {}

    def _has_valid_llm_credentials(self) -> bool:
        if not self._using_default_crawler:
            return True
        provider = self.settings.llm_provider.strip().lower()
        if provider == "ollama":
            return True
        token = (self.settings.gemini_api_key or "").strip()
        return bool(token and token != "your_gemini_api_key_here")

    @staticmethod
    def _needs_detail_parse(
        tour_row: Optional[Dict[str, Any]],
        force_reparse: bool = False,
        max_age_days: int = 7,
    ) -> bool:
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

    def _build_package_from_list_fallback(self, item: TourListItem) -> TourPackage:
        """當詳情頁尚未解析（受限單次上限、略過 LLM 或失敗）時，以清單欄位建立最小可用模型供試算。"""
        return TourPackage(
            trip_id=self.trip_config.trip_id if self.trip_config else item.trip_id,
            destination_country=self.trip_config.destination.country if self.trip_config else None,
            destination_region=self.trip_config.destination.region_name if self.trip_config else None,
            agency=item.agency,
            tour_code=item.tour_code,
            tour_name=item.tour_name,
            source_url=item.detail_url,
            days=item.days,
            nights=max(0, item.days - 1),
            departure_date=item.departure_date,
            departure_airport=(
                item.departure_airport
                if item.departure_airport in {"TPE", "KHH", "RMQ", "TSA", "OTHER"}
                else "OTHER"
            ),
            status=(
                item.status
                if item.status in {"可報名", "保證出團", "候補", "滿團", "已截止", "未知"}
                else "未知"
            ),
            seats_available=item.seats_available,
            pricing=PricingDetail(adult_twin_price=item.adult_price),
        )

    async def run_daily_pipeline(
        self,
        agencies: Optional[List[str]] = None,
        force_reparse: bool = False,
        max_new_details_per_run: Optional[int] = None,
        skip_flight_benchmark: bool = False,
        skip_llm: bool = False,
    ) -> Dict[str, Any]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        await init_db(self.repo.db_path)

        trip_id = self.trip_config.trip_id if self.trip_config else "default"
        trip_name = self.trip_config.trip_name if self.trip_config else "通用旅遊比價專案"
        dest_country = self.trip_config.destination.country if self.trip_config else None
        dest_airports = self.trip_config.destination.airports if self.trip_config else []
        primary_dest_airport = dest_airports[0] if dest_airports else None

        detail_limit = (
            max_new_details_per_run
            if max_new_details_per_run is not None
            else self.settings.max_new_details_per_run
        )

        llm_enabled = (not skip_llm) and detail_limit > 0 and self._has_valid_llm_credentials()
        if not llm_enabled and not skip_llm and detail_limit > 0:
            logger.info("[%s] 未設定有效 LLM 金鑰，本次巡檢自動略過詳情頁 LLM 解析（Zero-Infra 模式）。", trip_id)

        if self._custom_adapters is not None:
            adapters = self._custom_adapters
        else:
            agencies_cfg = load_agencies_config("config/agencies.yaml")
            adapters = build_enabled_adapters(
                agencies_cfg,
                target_keys=agencies,
                trip_config=self.trip_config,
                allow_playwright_fallback=self.allow_playwright_fallback,
            )

        discovered_items: List[TourListItem] = []
        agency_stats: Dict[str, Any] = {}
        errors: List[Dict[str, str]] = []
        alerts: List[AlertEvent] = []

        # 1. 上游清單抓取（併發=1，單社失敗不中斷整體）
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
                logger.error("[%s] 旅行社抓取失敗 [%s]: %s", trip_id, adapter.agency_name, err_msg)
                errors.append({"agency": adapter.agency_name, "error": err_msg})
                agency_stats[adapter.agency_name] = {
                    "count": 0,
                    "mode": "FAILED",
                    "status": "ERROR",
                }
                err_alert_key = f"AGENCY_CRAWL_ERROR:{trip_id}:{adapter.agency_key}:{run_id[:8]}"
                if not await self.repo.is_alert_logged(err_alert_key):
                    err_alert = AlertEvent(
                        alert_key=err_alert_key,
                        alert_type="AGENCY_CRAWL_ERROR",
                        tour_uid=None,
                        priority="維運",
                        message=f"[{trip_name}] 旅行社 [{adapter.agency_name}] 抓取失敗：{err_msg[:180]}",
                        details={"trip_id": trip_id, "agency": adapter.agency_name, "error": err_msg},
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                    alerts.append(err_alert)
                    await self.repo.insert_alert_log(
                        err_alert.alert_key, err_alert.alert_type, None, err_alert.message
                    )

        # 2. 多航線機票基準查詢
        flight_min_by_airport: Dict[str, int] = {}
        if not skip_flight_benchmark:
            try:
                if self.trip_config and self.trip_config.flight_benchmark.enabled and dest_airports:
                    fb_cfg = self.trip_config.flight_benchmark
                    depart_d = fb_cfg.sample_depart_date or self.trip_config.schedule.departure_date_start
                    return_d = fb_cfg.sample_return_date or self.trip_config.schedule.departure_date_end
                    bm_results = await self.flight_client.fetch_route_benchmarks(
                        origins=fb_cfg.origins,
                        destinations=dest_airports,
                        depart_date=depart_d,
                        return_date=return_d,
                        max_stops=fb_cfg.max_stops,
                    )
                    flight_min_by_airport = self.flight_client.summarize_min_by_origin(bm_results)
                elif self.trip_config is None:
                    bm_results = await self.flight_client.fetch_all_taiwan_oka_benchmarks()
                    for origin, bm in bm_results.items():
                        if bm.min_price_twd is not None:
                            flight_min_by_airport[origin] = bm.min_price_twd
            except Exception as exc:
                logger.warning("[%s] 機票基準查詢略過: %s", trip_id, exc)

        # 3. 增量比對 + 詳情解析 (7 天快取) + 雙層試算評分 + 事件驅動快照
        llm_calls_used = 0
        llm_skipped_cached = 0
        snapshots_inserted = 0
        ranked_results: List[RankedTourResult] = []
        snapshot_contexts: List[Dict[str, Any]] = []

        for item in discovered_items:
            tour_uid = await self.repo.upsert_tour_from_list(
                item,
                trip_id=trip_id,
                destination_country=dest_country,
                destination_airport=primary_dest_airport,
            )
            tour_row = await self.repo.get_tour(tour_uid)

            package: Optional[TourPackage] = None
            if self._needs_detail_parse(tour_row, force_reparse=force_reparse, max_age_days=7):
                if llm_enabled and llm_calls_used < detail_limit:
                    try:
                        if self.trip_config is not None:
                            package = await self.detail_crawler.parse_url(
                                url=item.detail_url,
                                agency_hint=item.agency,
                                trip_config=self.trip_config,
                            )
                        else:
                            package = await self.detail_crawler.parse_url(
                                url=item.detail_url,
                                agency_hint=item.agency,
                            )
                        await self.repo.update_tour_detail(tour_uid, package.model_dump_json())
                        llm_calls_used += 1
                    except Exception as exc:
                        logger.warning("詳情解析失敗 (%s): %s", tour_uid, exc)
                        errors.append({"tour_uid": tour_uid, "error": f"detail_parse: {exc}"})
            else:
                llm_skipped_cached += 1
                try:
                    package = TourPackage.model_validate_json(tour_row["detail_json"])
                except Exception:
                    package = None

            if package is None:
                package = self._build_package_from_list_fallback(item)

            package.trip_id = trip_id
            if dest_country and not package.destination_country:
                package.destination_country = dest_country

            # 以清單即時價格、機位與狀態覆寫靜態詳情
            if item.adult_price is not None:
                package.pricing.adult_twin_price = item.adult_price
            if item.seats_available is not None:
                package.seats_available = item.seats_available
            if item.status in {"可報名", "保證出團", "候補", "滿團", "已截止", "未知"}:
                package.status = item.status

            bm_price = flight_min_by_airport.get(package.departure_airport)
            budget_res = self.budget_engine.calculate(package, benchmark_flight_min_price=bm_price)
            eval_res = RuleEvaluator.evaluate(package, budget_res, trip_config=self.trip_config)
            budget_res.composite_score = eval_res.score

            await self.repo.update_tour_evaluation(tour_uid, eval_res.score, eval_res.tags)

            # 事件驅動寫入快照（僅首次出現或價格/機位/狀態變動才新增）
            was_inserted, _ = await self.repo.insert_price_snapshot_if_changed(
                tour_uid=tour_uid,
                adult_price=item.adult_price or package.pricing.adult_twin_price,
                seats_available=(
                    item.seats_available
                    if item.seats_available is not None
                    else package.seats_available
                ),
                status=package.status,
                estimated_family_total=budget_res.grand_total_twd,
            )
            if was_inserted:
                snapshots_inserted += 1

            ranked_results.append(
                RankedTourResult(
                    trip_id=trip_id,
                    tour_uid=tour_uid,
                    agency=item.agency,
                    tour_name=package.tour_name,
                    departure_date=item.departure_date,
                    days=item.days,
                    departure_airport=item.departure_airport,
                    adult_price=item.adult_price or package.pricing.adult_twin_price,
                    seats_available=package.seats_available,
                    status=package.status,
                    detail_url=item.detail_url,
                    budget=budget_res,
                    composite_score=eval_res.score,
                    tags=eval_res.tags,
                    passed_rules=eval_res.passed_rules,
                    failed_rules=eval_res.failed_rules,
                )
            )
            snapshot_contexts.append(
                {
                    "tour_uid": tour_uid,
                    "item": item,
                    "package": package,
                    "budget": budget_res,
                    "snapshot_changed": was_inserted,
                }
            )

        # 依綜合評分高到低、總價低到高排序
        ranked_results.sort(key=lambda r: (-r.composite_score, r.budget.grand_total_twd))
        top_5_uids = {r.tour_uid for r in ranked_results[:5]}

        # 4. 差異比對與異動告警偵測
        for ctx in snapshot_contexts:
            if not ctx["snapshot_changed"]:
                continue
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

        diff_report = DiffEngine.build_report(alerts)
        diff_summary = diff_report.to_summary_dict()

        # 5. 寫入巡檢審計表 scan_history
        await self.repo.insert_scan_history(
            trip_id=trip_id,
            agencies_run=list(agency_stats.keys()),
            total_found=len(discovered_items),
            new_count=diff_summary["new_count"],
            price_drop_count=diff_summary["price_drop_count"],
            seats_released_count=diff_summary["seats_released_count"],
            status_change_count=diff_summary["guaranteed_count"] + diff_summary["low_seats_count"],
            error_summary="; ".join(f"{e.get('agency') or e.get('tour_uid')}: {e.get('error')}" for e in errors)[:500]
            if errors
            else None,
            cli_args={
                "agencies": agencies,
                "force_reparse": force_reparse,
                "max_new_details_per_run": detail_limit,
                "skip_flight_benchmark": skip_flight_benchmark,
                "skip_llm": skip_llm,
                "allow_playwright_fallback": self.allow_playwright_fallback,
            },
        )

        return {
            "run_id": run_id,
            "trip_id": trip_id,
            "trip_name": trip_name,
            "status": "PARTIAL_SUCCESS" if errors else "SUCCESS",
            "stats": {
                "total_discovered": len(discovered_items),
                "snapshots_inserted": snapshots_inserted,
                "llm_calls_used": llm_calls_used,
                "llm_skipped_cached": llm_skipped_cached,
                "alerts_count": len(alerts),
                "agencies": agency_stats,
                "flight_benchmarks_twd": flight_min_by_airport,
            },
            "diff_summary": diff_summary,
            "alerts": [a.model_dump() for a in alerts],
            "top_5_rankings": [r.model_dump() for r in ranked_results[:5]],
            "rankings": [r.model_dump() for r in ranked_results],
            "errors": errors,
        }
