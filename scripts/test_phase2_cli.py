from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path

# 確保專案根目錄在 sys.path 中
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.calculator.budget_engine import BudgetEngine
from src.config import get_settings, load_family_profile
from src.db.database import init_db
from src.db.repository import TourRepository
from src.extractor.detail_crawler import DetailCrawler
from src.extractor.flight_benchmark import FlightBenchmarkClient
from src.schemas.discovery_schema import TourListItem


async def run_cli(args: argparse.Namespace) -> int:
    settings = get_settings()
    db_path = args.db_path or settings.database_path
    await init_db(db_path)
    repo = TourRepository(db_path)

    benchmark_min_by_airport = {}

    if not args.skip_flights:
        print(f"=== 1. 查詢 Google Flights 機票基準 ({args.depart_date} ~ {args.return_date}) ===")
        flight_client = FlightBenchmarkClient(repository=repo)
        benchmarks = await flight_client.fetch_all_taiwan_oka_benchmarks(
            depart_date=args.depart_date,
            return_date=args.return_date,
        )
        for origin, res in benchmarks.items():
            if res.error:
                print(f"[{origin}->OKA] 查詢失敗: {res.error}")
            else:
                print(
                    f"[{origin}->OKA] 最低價: NT$ {res.min_price_twd} | "
                    f"中位數: NT$ {res.median_price_twd} | 航班數: {res.flight_count}"
                )
                if res.min_price_twd is not None:
                    benchmark_min_by_airport[origin] = res.min_price_twd

    if args.url:
        print(f"\n=== 2. 使用 Crawl4AI 解析詳情頁 ({args.url}) ===")
        crawler = DetailCrawler(settings=settings)
        package = await crawler.parse_url(url=args.url, agency_hint=args.agency)
        print("解析結果 (OkinawaTourPackage JSON):")
        print(package.model_dump_json(indent=2))

        # 寫入 SQLite tours 表
        list_item = TourListItem(
            agency=package.agency if package.agency != "其他" else (args.agency or "雄獅旅遊"),
            tour_code=package.tour_code or "MANUAL_CLI",
            tour_name=package.tour_name,
            departure_date=package.departure_date or args.depart_date,
            days=package.days,
            departure_airport=package.departure_airport,
            adult_price=package.pricing.adult_twin_price,
            seats_available=package.seats_available,
            status=package.status,
            detail_url=args.url,
            raw_hash="manual_cli",
        )
        tour_uid = await repo.upsert_tour_from_list(list_item)
        await repo.update_tour_detail(tour_uid, package.model_dump_json())
        print(f"\n已成功寫入資料庫 {db_path} (tour_uid={tour_uid})")

        # 執行家族總預算試算
        print("\n=== 3. 家族真實總預算試算結果 ===")
        profile = load_family_profile("config/family_profile.yaml")
        engine = BudgetEngine(profile)
        benchmark_price = benchmark_min_by_airport.get(package.departure_airport)
        budget_res = engine.calculate(package, benchmark_flight_min_price=benchmark_price)
        print(json.dumps(budget_res.model_dump(), ensure_ascii=False, indent=2))

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2 CLI 測試工具：Crawl4AI 詳情頁解析 + fast-flights 機票基準 + 家族試算"
    )
    parser.add_argument("--url", type=str, default=None, help="要解析的旅行社沖繩行程詳情頁網址")
    parser.add_argument(
        "--agency",
        type=str,
        default=None,
        choices=["可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊"],
        help="旅行社名稱提示",
    )
    parser.add_argument("--depart-date", type=str, default="2027-02-04", help="機票基準出發日 (YYYY-MM-DD)")
    parser.add_argument("--return-date", type=str, default="2027-02-08", help="機票基準回程日 (YYYY-MM-DD)")
    parser.add_argument("--skip-flights", action="store_true", help="略過 fast-flights 查詢")
    parser.add_argument("--db-path", type=str, default=None, help="指定 SQLite 資料庫路徑")

    args = parser.parse_args()
    if not args.url and args.skip_flights:
        parser.error("請至少提供 --url 或不要加上 --skip-flights。")

    exit_code = asyncio.run(run_cli(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
