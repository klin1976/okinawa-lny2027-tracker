from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.calculator.budget_engine import BudgetEngine
from src.config import get_settings
from src.db.database import init_db
from src.db.repository import TourRepository
from src.extractor.detail_crawler import DetailCrawler, DetailExtractionError
from src.schemas.budget_schema import RankedTourResult
from src.schemas.tour_schema import OkinawaTourPackage, PricingDetail
from src.services.pipeline_service import PipelineService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db(settings.database_path)
    yield


app = FastAPI(
    title="Okinawa LNY 2027 Tour Tracker API",
    version="1.0.0",
    description="2027 春節沖繩旅遊跨社比價與監控系統 API",
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
    url: str = Field(..., min_length=1, description="旅行社沖繩行程詳情頁網址")
    agency_hint: Optional[str] = Field(
        default=None,
        description="旅行社名稱提示（如：雄獅旅遊、可樂旅遊）",
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


@app.post("/api/v1/pipeline/daily-run", dependencies=[Depends(verify_api_key)])
async def run_daily_pipeline(
    payload: DailyRunRequest = Body(default_factory=DailyRunRequest),
) -> Dict[str, Any]:
    """主排程進入點：依序執行清單抓取、增量詳情解析、機票基準、家族預算試算與告警偵測。"""
    settings = get_settings()
    service = PipelineService(settings=settings)
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
    crawler = DetailCrawler(settings=settings)
    try:
        tour = await crawler.parse_url(url=payload.url, agency_hint=payload.agency_hint)
    except DetailExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    engine = BudgetEngine()
    budget = engine.calculate(tour)
    return {
        "tour": tour.model_dump(),
        "budget": budget.model_dump(),
    }


@app.get("/api/v1/rankings", dependencies=[Depends(verify_api_key)])
async def get_rankings(
    airport: Optional[str] = Query(default=None, description="篩選台灣出發機場代碼（如 TPE, KHH, RMQ）"),
    no_shopping: bool = Query(default=False, description="是否僅保留無購物站行程"),
    only_enough_seats: bool = Query(default=False, description="是否僅保留剩餘機位足夠全家族的行程"),
    limit: int = Query(default=20, ge=1, le=200, description="回傳筆數上限"),
) -> Dict[str, Any]:
    """取得最新一輪活躍團次的家族總價與性價比排行榜。"""
    settings = get_settings()
    repo = TourRepository(settings.database_path)
    engine = BudgetEngine()

    active_tours = await repo.get_all_active_tours()
    airport_filter = airport.strip().upper() if airport else None

    ranked: List[RankedTourResult] = []
    valid_agencies = {"可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊", "其他"}
    valid_airports = {"TPE", "KHH", "RMQ", "TSA", "OTHER"}
    valid_statuses = {"可報名", "保證出團", "候補", "滿團", "已截止", "未知"}

    for tour_row in active_tours:
        row_airport = (tour_row.get("departure_airport") or "OTHER").upper()
        if airport_filter and row_airport != airport_filter:
            continue

        package: Optional[OkinawaTourPackage] = None
        detail_json = tour_row.get("detail_json")
        if detail_json:
            try:
                package = OkinawaTourPackage.model_validate_json(detail_json)
            except Exception:
                package = None

        if package is None:
            raw_days = int(tour_row.get("days") or 4)
            clamped_days = max(1, min(5, raw_days))
            package = OkinawaTourPackage(
                agency=tour_row["agency"] if tour_row.get("agency") in valid_agencies else "其他",
                tour_code=tour_row.get("tour_code"),
                tour_name=tour_row["tour_name"],
                source_url=tour_row.get("detail_url"),
                days=clamped_days,
                nights=max(0, min(4, clamped_days - 1)),
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

        bm_price: Optional[int] = None
        if tour_row.get("departure_date"):
            bm = await repo.get_latest_flight_benchmark(
                package.departure_airport, "OKA", tour_row["departure_date"]
            )
            if bm:
                bm_price = bm.get("min_price_twd")

        budget_res = engine.calculate(package, benchmark_flight_min_price=bm_price)

        if no_shopping and package.comparison_flags.has_shopping_station:
            continue
        if only_enough_seats and budget_res.seat_status != "SUFFICIENT":
            continue

        ranked.append(
            RankedTourResult(
                tour_uid=tour_row["tour_uid"],
                agency=tour_row["agency"],
                tour_name=package.tour_name,
                departure_date=tour_row["departure_date"],
                days=tour_row["days"],
                departure_airport=row_airport,
                adult_price=package.pricing.adult_twin_price,
                seats_available=package.seats_available,
                detail_url=tour_row["detail_url"],
                budget=budget_res,
                composite_score=budget_res.composite_score,
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
