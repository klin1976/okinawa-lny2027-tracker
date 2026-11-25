from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.calculator.budget_engine import BudgetEngine
from src.config import get_settings, list_trip_configs
from src.db.database import get_db_path
from src.db.repository import TourRepository
from src.evaluator import RuleEvaluator
from src.schemas.budget_schema import RankedTourResult
from src.schemas.tour_schema import PricingDetail, TourPackage
from src.schemas.trip_schema import TripConfig
from src.web.catalog import build_destination_catalog

VALID_AGENCIES = {"可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊", "其他"}
VALID_AIRPORTS = {"TPE", "KHH", "RMQ", "TSA", "OTHER"}
VALID_STATUSES = {"可報名", "保證出團", "候補", "滿團", "已截止", "未知"}
SNAPSHOT_KEEP_KEYS = (
    "captured_at",
    "adult_price",
    "seats_available",
    "status",
    "estimated_family_total",
)


def _compact_snapshots(
    snapshots: List[Dict[str, Any]], max_items: int = 30
) -> List[Dict[str, Any]]:
    """精簡每團歷史快照欄位與筆數，控制靜態 JSON 體積。"""
    tail = snapshots[-max_items:] if max_items > 0 else snapshots
    return [{k: s.get(k) for k in SNAPSHOT_KEEP_KEYS} for s in tail]


def _package_from_row(
    tour_row: Dict[str, Any], row_trip_id: str, row_airport: str
) -> TourPackage:
    """從資料表紀錄還原或組裝 TourPackage。"""
    detail_json = tour_row.get("detail_json")
    if detail_json:
        try:
            return TourPackage.model_validate_json(detail_json)
        except Exception:
            pass

    raw_days = int(tour_row.get("days") or 4)
    clamped_days = max(1, min(30, raw_days))
    agency = tour_row.get("agency")
    return TourPackage(
        trip_id=row_trip_id,
        destination_country=tour_row.get("destination_country"),
        agency=agency if agency in VALID_AGENCIES else "其他",
        tour_code=tour_row.get("tour_code") or "",
        tour_name=tour_row.get("tour_name") or "",
        source_url=tour_row.get("detail_url") or "",
        days=clamped_days,
        nights=max(0, min(29, clamped_days - 1)),
        departure_date=tour_row.get("departure_date") or "",
        departure_airport=row_airport if row_airport in VALID_AIRPORTS else "OTHER",
        pricing=PricingDetail(),
    )


def _build_trip_summary(trip_cfg: TripConfig, engine: BudgetEngine) -> Dict[str, Any]:
    """建立前端切換列所需的旅遊專案摘要。"""
    demands = engine.calculate_demands()
    target_budget = trip_cfg.party.target_total_budget_twd
    if target_budget is None:
        target_budget = engine.profile.get("target_total_budget_twd")

    return {
        "trip_id": trip_cfg.trip_id,
        "trip_name": trip_cfg.trip_name,
        "enabled": trip_cfg.enabled,
        "country": trip_cfg.destination.country,
        "region_name": trip_cfg.destination.region_name,
        "airports": list(trip_cfg.destination.airports),
        "departure_date_start": trip_cfg.schedule.departure_date_start,
        "departure_date_end": trip_cfg.schedule.departure_date_end,
        "min_days": trip_cfg.schedule.min_days,
        "max_days": trip_cfg.schedule.max_days,
        "child_bed_age_threshold": trip_cfg.party.child_bed_age_threshold,
        "target_total_budget_twd": target_budget,
        "total_members": demands["total_pax"],
    }


def _summarize_default_party(engine: BudgetEngine) -> Dict[str, int]:
    """將預設家族設定檔轉為成人與兒童人數摘要。"""
    adults = 0
    children_with_bed = 0
    children_no_bed = 0
    infants = 0
    for m in engine.members:
        role = m.get("role", "adult")
        count = int(m.get("count", 1))
        age = m.get("age")
        require_bed = m.get("require_bed", True)
        if role in ("adult", "senior"):
            adults += count
        elif role == "child":
            if require_bed or (age is not None and age >= engine.child_bed_age_threshold):
                children_with_bed += count
            else:
                children_no_bed += count
        elif role == "infant":
            infants += count
    return {
        "adults": adults,
        "children_with_bed": children_with_bed,
        "children_no_bed": children_no_bed,
        "infants": infants,
        "total": adults + children_with_bed + children_no_bed + infants,
    }


def _build_pricing_params(package: TourPackage, engine: BudgetEngine) -> Dict[str, Any]:
    """萃取供前端即時重算成人/兒童預算的精簡計價參數。"""
    cp = package.pricing.child_pricing
    triple_policy = (package.pricing.triple_room_policy or "").lower()
    no_triple_keywords = ("無法加床", "無三人房", "不提供三人房", "不可加床", "無法提供加床")
    allows_triple = not any(k in triple_policy for k in no_triple_keywords)
    return {
        "adult_twin_price": package.pricing.adult_twin_price,
        "child_with_bed_price": cp.child_with_bed_price,
        "child_with_bed_diff": cp.child_with_bed_diff,
        "child_no_bed_price": cp.child_no_bed_price,
        "child_no_bed_diff": cp.child_no_bed_diff,
        "infant_price": cp.infant_under_2_price,
        "tip_per_day_twd": package.pricing.tip_per_day_twd,
        "single_room_supplement": package.pricing.single_room_supplement,
        "allows_triple_room": allows_triple,
        "default_tip_per_day": engine.defaults.get("tip_per_day_twd", 300),
        "fallback_child_no_bed_diff": engine.defaults.get(
            "fallback_child_no_bed_diff", -3000
        ),
        "fallback_infant_price": engine.defaults.get("fallback_infant_price", 6000),
        "fallback_single_room_supplement": engine.defaults.get(
            "fallback_single_room_supplement", 12000
        ),
        "prefer_triple_room_for_odd_pax": engine.rooming.get(
            "prefer_triple_room_for_odd_pax", True
        ),
        "child_bed_age_threshold": engine.child_bed_age_threshold,
    }


async def build_dashboard_payload(
    db_path: Optional[str] = None,
    trips_dir: str = "config/trips",
    diff_hours: int = 168,
    scan_limit: int = 30,
) -> Dict[str, Any]:
    """組裝靜態匯出與 /api/v1/dashboard 共用的完整儀表板資料集。"""
    settings = get_settings()
    resolved_db = get_db_path(db_path or settings.database_path)
    trips = list_trip_configs(trips_dir=trips_dir, enabled_only=False)

    trips_map: Dict[str, TripConfig] = {t.trip_id: t for t in trips}
    engine_cache: Dict[str, BudgetEngine] = {}
    trip_summaries: List[Dict[str, Any]] = []
    for trip_cfg in trips:
        eng = BudgetEngine(trip_cfg)
        engine_cache[trip_cfg.trip_id] = eng
        trip_summaries.append(_build_trip_summary(trip_cfg, eng))

    default_engine = BudgetEngine()

    last_run_at: Optional[str] = None
    active_tours: List[Dict[str, Any]] = []
    snapshots_map: Dict[str, List[Dict[str, Any]]] = {}
    recent_diffs: List[Dict[str, Any]] = []
    scan_history: List[Dict[str, Any]] = []

    if Path(resolved_db).exists():
        repo = TourRepository(resolved_db)
        try:
            last_run_at = await repo.get_last_snapshot_time()
            active_tours = await repo.get_all_active_tours()
            tour_uids = [str(row["tour_uid"]) for row in active_tours]
            snapshots_map = await repo.get_all_snapshots_grouped(tour_uids=tour_uids)
            recent_diffs = await repo.get_recent_snapshot_diffs(
                hours=diff_hours, limit=100
            )
            scan_history = await repo.get_recent_scan_history(limit=scan_limit)
        except Exception:
            # 若資料庫尚未初始化完成，回傳空資料集避免中斷
            last_run_at = None
            active_tours = []
            snapshots_map = {}
            recent_diffs = []
            scan_history = []
    else:
        repo = None

    benchmark_cache: Dict[Tuple[str, str, str], Optional[int]] = {}
    evaluated_tours: List[Dict[str, Any]] = []

    for tour_row in active_tours:
        tour_uid = str(tour_row["tour_uid"])
        row_airport = (tour_row.get("departure_airport") or "OTHER").upper()
        row_trip_id = str(tour_row.get("trip_id") or "default")
        row_trip_cfg = trips_map.get(row_trip_id)

        package = _package_from_row(tour_row, row_trip_id, row_airport)
        tour_snaps = snapshots_map.get(tour_uid, [])
        latest_snap = tour_snaps[-1] if tour_snaps else None

        if latest_snap:
            if latest_snap.get("adult_price") is not None:
                package.pricing.adult_twin_price = latest_snap["adult_price"]
            if latest_snap.get("seats_available") is not None:
                package.seats_available = latest_snap["seats_available"]
            if latest_snap.get("status") in VALID_STATUSES:
                package.status = latest_snap["status"]

        dest_airport = tour_row.get("destination_airport") or (
            row_trip_cfg.destination.airports[0]
            if row_trip_cfg and row_trip_cfg.destination.airports
            else None
        )
        bm_price: Optional[int] = None
        dep_date = tour_row.get("departure_date")
        if repo is not None and dep_date and dest_airport:
            bm_key = (package.departure_airport, str(dest_airport), str(dep_date))
            if bm_key not in benchmark_cache:
                bm = await repo.get_latest_flight_benchmark(*bm_key)
                benchmark_cache[bm_key] = bm.get("min_price_twd") if bm else None
            bm_price = benchmark_cache[bm_key]

        row_engine = (
            engine_cache[row_trip_cfg.trip_id]
            if row_trip_cfg and row_trip_cfg.trip_id in engine_cache
            else default_engine
        )
        budget_res = row_engine.calculate(package, benchmark_flight_min_price=bm_price)
        eval_res = RuleEvaluator.evaluate(package, budget_res, trip_config=row_trip_cfg)
        budget_res.composite_score = eval_res.score

        ranked = RankedTourResult(
            trip_id=row_trip_id,
            tour_uid=tour_uid,
            agency=tour_row["agency"],
            tour_name=package.tour_name,
            departure_date=tour_row["departure_date"],
            days=tour_row["days"],
            departure_airport=row_airport,
            adult_price=package.pricing.adult_twin_price,
            seats_available=package.seats_available,
            status=package.status,
            detail_url=tour_row["detail_url"],
            budget=budget_res,
            composite_score=eval_res.score,
            tags=eval_res.tags,
            passed_rules=eval_res.passed_rules,
            failed_rules=eval_res.failed_rules,
        )
        item_dict = ranked.model_dump()
        item_dict["has_shopping_station"] = bool(
            package.comparison_flags.has_shopping_station
        )
        item_dict["destination_country"] = tour_row.get("destination_country") or (
            row_trip_cfg.destination.country if row_trip_cfg else ""
        )
        item_dict["destination_region"] = (
            row_trip_cfg.destination.region_name if row_trip_cfg else ""
        )
        item_dict["pricing_params"] = _build_pricing_params(package, row_engine)
        item_dict["detail_parsed_at"] = tour_row.get("detail_parsed_at")
        item_dict["tour_code"] = tour_row.get("tour_code")
        item_dict["snapshots"] = _compact_snapshots(tour_snaps, max_items=30)
        evaluated_tours.append(item_dict)

    evaluated_tours.sort(
        key=lambda r: (-float(r["composite_score"]), int(r["budget"]["grand_total_twd"]))
    )

    agencies = sorted({str(t["agency"]) for t in evaluated_tours})
    destinations_catalog = build_destination_catalog(trips)
    default_party = _summarize_default_party(default_engine)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_run_at": last_run_at,
        "summary": {
            "total_active_tours": len(evaluated_tours),
            "agencies": agencies,
            "trips_count": len(trip_summaries),
            "diffs_count": len(recent_diffs),
        },
        "destinations_catalog": destinations_catalog,
        "default_party": default_party,
        "trips": trip_summaries,
        "tours": evaluated_tours,
        "recent_diffs": recent_diffs,
        "scan_history": scan_history,
    }


async def export_dashboard_json(
    output_path: str | Path = "web/data/dashboard.json",
    db_path: Optional[str] = None,
    trips_dir: str = "config/trips",
    diff_hours: int = 168,
    scan_limit: int = 30,
) -> Dict[str, Any]:
    """將儀表板資料集匯出為 UTF-8 靜態 JSON 檔供 GitHub Pages 使用。"""
    payload = await build_dashboard_payload(
        db_path=db_path,
        trips_dir=trips_dir,
        diff_hours=diff_hours,
        scan_limit=scan_limit,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    target.write_text(content, encoding="utf-8")

    return {
        "output_path": str(target),
        "bytes_written": target.stat().st_size,
        "total_active_tours": payload["summary"]["total_active_tours"],
        "trips_count": payload["summary"]["trips_count"],
        "diffs_count": payload["summary"]["diffs_count"],
        "generated_at": payload["generated_at"],
    }


def export_dashboard_json_sync(
    output_path: str | Path = "web/data/dashboard.json",
    db_path: Optional[str] = None,
    trips_dir: str = "config/trips",
    diff_hours: int = 168,
    scan_limit: int = 30,
) -> Dict[str, Any]:
    """同步包裝 export_dashboard_json。"""
    return asyncio.run(
        export_dashboard_json(
            output_path=output_path,
            db_path=db_path,
            trips_dir=trips_dir,
            diff_hours=diff_hours,
            scan_limit=scan_limit,
        )
    )
