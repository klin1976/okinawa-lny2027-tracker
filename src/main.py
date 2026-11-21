from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.calculator.budget_engine import BudgetEngine
from src.config import get_settings, list_trip_configs, load_trip_config
from src.db.database import init_db
from src.db.repository import TourRepository
from src.evaluator import RuleEvaluator
from src.extractor.detail_crawler import DetailCrawler, DetailExtractionError
from src.schemas.budget_schema import RankedTourResult
from src.schemas.tour_schema import PricingDetail, TourPackage
from src.schemas.trip_schema import TripConfig
from src.services.pipeline_service import PipelineService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db(settings.database_path)
    yield


app = FastAPI(
    title="Travel Radar API",
    version="2.0.0",
    description="通用多目的地旅遊跨社比價與異動監控雷達 API（選配 Web 服務層）",
    lifespan=lifespan,
)


def verify_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> str:
    """驗證請求 Header 中的 X-API-Key。"""
    settings = get_settings()
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )
    return x_api_key


class DailyRunRequest(BaseModel):
    trip_id: Optional[str] = Field(
        default=None,
        description="指定執行的旅遊專案 ID（如 okinawa_lny2027、europe_summer2027），未指定則使用預設專案",
    )
    agencies: Optional[List[str]] = Field(
        default=None,
        description="指定執行的旅行社 key 或名稱清單，預設全部啟用（可傳 ['all']）",
    )
    force_reparse: bool = Field(
        default=False,
        description="是否強制忽略 7 天快取並重新以 LLM 解析詳情頁",
    )
    max_new_details_per_run: Optional[int] = Field(
        default=None,
        ge=0,
        description="單次排程最多呼叫 LLM 解析的新詳情頁數量上限",
    )
    skip_flight_benchmark: bool = Field(
        default=False,
        description="是否略過 fast-flights 同期機票基準查詢",
    )


class ExtractSingleRequest(BaseModel):
    url: str = Field(..., min_length=1, description="旅行社行程詳情頁網址")
    agency_hint: Optional[str] = Field(
        default=None,
        description="旅行社名稱提示（如：雄獅旅遊、可樂旅遊）",
    )
    trip_id: Optional[str] = Field(
        default=None,
        description="選填：套用的旅遊專案 ID（以套用對應國家的佔床與小費規則）",
    )


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """容器健康檢查（無須驗證）：檢查 SQLite 連線與最後快照時間。"""
    settings = get_settings()
    repo = TourRepository(settings.database_path)
    db_connected = await repo.check_connection()
    last_run_at = await repo.get_last_snapshot_time() if db_connected else None
    return {
        "status": "ok" if db_connected else "error",
        "db_connected": db_connected,
        "last_run_at": last_run_at,
    }


@app.get("/api/v1/trips", dependencies=[Depends(verify_api_key)])
async def get_trips(
    enabled_only: bool = Query(default=False, description="是否僅回傳 enabled=true 的旅遊專案"),
) -> Dict[str, Any]:
    """列出系統設定目錄下所有多目的地旅遊專案摘要。"""
    settings = get_settings()
    trips = list_trip_configs(trips_dir=settings.trips_dir, enabled_only=enabled_only)
    return {
        "total": len(trips),
        "trips": [
            {
                "trip_id": t.trip_id,
                "trip_name": t.trip_name,
                "enabled": t.enabled,
                "country": t.destination.country,
                "region_name": t.destination.region_name,
                "airports": t.destination.airports,
                "departure_date_start": t.schedule.departure_date_start,
                "departure_date_end": t.schedule.departure_date_end,
                "min_days": t.schedule.min_days,
                "max_days": t.schedule.max_days,
                "child_bed_age_threshold": t.party.child_bed_age_threshold,
                "target_total_budget_twd": t.party.target_total_budget_twd,
            }
            for t in trips
        ],
    }


@app.post("/api/v1/pipeline/daily-run", dependencies=[Depends(verify_api_key)])
async def run_daily_pipeline(
    payload: DailyRunRequest = Body(default_factory=DailyRunRequest),
) -> Dict[str, Any]:
    """主排程進入點：依序執行清單抓取、增量詳情解析、機票基準、家族預算試算與告警偵測。"""
    settings = get_settings()
    trip_cfg: Optional[TripConfig] = None
    if payload.trip_id:
        try:
            trip_cfg = load_trip_config(payload.trip_id, trips_dir=settings.trips_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    service = PipelineService(settings=settings, trip_config=trip_cfg)
    return await service.run_daily_pipeline(
        agencies=payload.agencies,
        force_reparse=payload.force_reparse,
        max_new_details_per_run=payload.max_new_details_per_run,
        skip_flight_benchmark=payload.skip_flight_benchmark,
    )


@app.post("/api/v1/extract/single", dependencies=[Depends(verify_api_key)])
async def extract_single_tour(payload: ExtractSingleRequest) -> Dict[str, Any]:
    """手動傳入單一詳情頁網址，執行 Crawl4AI + LLM 解析並立即進行家族預算試算。"""
    settings = get_settings()
    trip_cfg: Optional[TripConfig] = None
    if payload.trip_id:
        try:
            trip_cfg = load_trip_config(payload.trip_id, trips_dir=settings.trips_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    crawler = DetailCrawler(settings=settings)
    try:
        if trip_cfg is not None:
            tour = await crawler.parse_url(
                url=payload.url,
                agency_hint=payload.agency_hint,
                trip_config=trip_cfg,
            )
        else:
            tour = await crawler.parse_url(url=payload.url, agency_hint=payload.agency_hint)
    except DetailExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    engine = BudgetEngine(trip_cfg) if trip_cfg is not None else BudgetEngine()
    budget = engine.calculate(tour)
    eval_res = RuleEvaluator.evaluate(tour, budget, trip_config=trip_cfg)
    budget.composite_score = eval_res.score
    return {
        "tour": tour.model_dump(),
        "budget": budget.model_dump(),
        "evaluation": {
            "is_passed": eval_res.is_passed,
            "score": eval_res.score,
            "tags": eval_res.tags,
            "passed_rules": eval_res.passed_rules,
            "failed_rules": eval_res.failed_rules,
        },
    }


@app.get("/api/v1/rankings", dependencies=[Depends(verify_api_key)])
async def get_rankings(
    trip_id: Optional[str] = Query(default=None, description="篩選特定旅遊專案 ID"),
    airport: Optional[str] = Query(default=None, description="篩選台灣出發機場代碼（如 TPE, KHH, RMQ）"),
    no_shopping: bool = Query(default=False, description="是否僅保留無購物站行程"),
    only_enough_seats: bool = Query(default=False, description="是否僅保留剩餘機位足夠全家族的行程"),
    limit: int = Query(default=20, ge=1, le=200, description="回傳筆數上限"),
) -> Dict[str, Any]:
    """取得最新一輪活躍團次的家族總價與性價比排行榜。"""
    settings = get_settings()
    repo = TourRepository(settings.database_path)

    trips_map: Dict[str, TripConfig] = {
        t.trip_id: t for t in list_trip_configs(trips_dir=settings.trips_dir, enabled_only=False)
    }
    requested_trip_cfg: Optional[TripConfig] = None
    if trip_id:
        requested_trip_cfg = trips_map.get(trip_id)
        if requested_trip_cfg is None:
            try:
                requested_trip_cfg = load_trip_config(trip_id, trips_dir=settings.trips_dir)
                trips_map[trip_id] = requested_trip_cfg
            except FileNotFoundError:
                requested_trip_cfg = None

    default_engine = BudgetEngine(requested_trip_cfg) if requested_trip_cfg else BudgetEngine()
    engine_cache: Dict[str, BudgetEngine] = {}

    active_tours = await repo.get_all_active_tours(trip_id=trip_id)
    airport_filter = airport.strip().upper() if airport else None

    ranked: List[RankedTourResult] = []
    valid_agencies = {"可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊", "其他"}
    valid_airports = {"TPE", "KHH", "RMQ", "TSA", "OTHER"}
    valid_statuses = {"可報名", "保證出團", "候補", "滿團", "已截止", "未知"}

    for tour_row in active_tours:
        row_airport = (tour_row.get("departure_airport") or "OTHER").upper()
        if airport_filter and row_airport != airport_filter:
            continue

        row_trip_id = str(tour_row.get("trip_id") or "default")
        row_trip_cfg = requested_trip_cfg or trips_map.get(row_trip_id)

        package: Optional[TourPackage] = None
        detail_json = tour_row.get("detail_json")
        if detail_json:
            try:
                package = TourPackage.model_validate_json(detail_json)
            except Exception:
                package = None

        if package is None:
            raw_days = int(tour_row.get("days") or 4)
            clamped_days = max(1, min(30, raw_days))
            package = TourPackage(
                trip_id=row_trip_id,
                destination_country=tour_row.get("destination_country"),
                agency=tour_row["agency"] if tour_row.get("agency") in valid_agencies else "其他",
                tour_code=tour_row.get("tour_code"),
                tour_name=tour_row["tour_name"],
                source_url=tour_row.get("detail_url"),
                days=clamped_days,
                nights=max(0, min(29, clamped_days - 1)),
                departure_date=tour_row.get("departure_date"),
                departure_airport=row_airport if row_airport in valid_airports else "OTHER",
                pricing=PricingDetail(),
            )

        latest_snap = await repo.get_latest_snapshot(tour_row["tour_uid"])
        if latest_snap:
            if latest_snap.get("adult_price") is not None:
                package.pricing.adult_twin_price = latest_snap["adult_price"]
            if latest_snap.get("seats_available") is not None:
                package.seats_available = latest_snap["seats_available"]
            if latest_snap.get("status") in valid_statuses:
                package.status = latest_snap["status"]

        dest_airport = tour_row.get("destination_airport") or (
            row_trip_cfg.destination.airports[0]
            if row_trip_cfg and row_trip_cfg.destination.airports
            else None
        )
        bm_price: Optional[int] = None
        if tour_row.get("departure_date") and dest_airport:
            bm = await repo.get_latest_flight_benchmark(
                package.departure_airport, dest_airport, tour_row["departure_date"]
            )
            if bm:
                bm_price = bm.get("min_price_twd")

        if row_trip_cfg is not None:
            if row_trip_cfg.trip_id not in engine_cache:
                engine_cache[row_trip_cfg.trip_id] = BudgetEngine(row_trip_cfg)
            row_engine = engine_cache[row_trip_cfg.trip_id]
        else:
            row_engine = default_engine

        budget_res = row_engine.calculate(package, benchmark_flight_min_price=bm_price)
        eval_res = RuleEvaluator.evaluate(package, budget_res, trip_config=row_trip_cfg)
        budget_res.composite_score = eval_res.score

        if no_shopping and package.comparison_flags.has_shopping_station:
            continue
        if only_enough_seats and budget_res.seat_status != "SUFFICIENT":
            continue

        ranked.append(
            RankedTourResult(
                trip_id=row_trip_id,
                tour_uid=tour_row["tour_uid"],
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
        )

    ranked.sort(key=lambda r: (-r.composite_score, r.budget.grand_total_twd))
    return {
        "total": len(ranked),
        "rankings": [r.model_dump() for r in ranked[:limit]],
    }


@app.get("/api/v1/tours/{tour_uid}/history", dependencies=[Depends(verify_api_key)])
async def get_tour_history(tour_uid: str) -> Dict[str, Any]:
    """查詢特定團次的元資料與歷史價格／機位快照時間序列。"""
    settings = get_settings()
    repo = TourRepository(settings.database_path)

    tour = await repo.get_tour(tour_uid)
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tour not found: {tour_uid}",
        )

    snapshots = await repo.get_snapshots_history(tour_uid)
    return {
        "tour_uid": tour["tour_uid"],
        "trip_id": tour.get("trip_id", "default"),
        "destination_country": tour.get("destination_country"),
        "destination_airport": tour.get("destination_airport"),
        "agency": tour["agency"],
        "tour_code": tour["tour_code"],
        "tour_name": tour["tour_name"],
        "departure_date": tour["departure_date"],
        "days": tour["days"],
        "departure_airport": tour["departure_airport"],
        "detail_url": tour["detail_url"],
        "is_active": bool(tour["is_active"]),
        "detail_parsed_at": tour["detail_parsed_at"],
        "price_snapshots": snapshots,
    }
