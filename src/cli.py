"""
通用旅遊比價與異動監控雷達 (travel-radar) 命令列入口 (CLI-First)。
支援子指令：init-db, list-trips, scan, diff, test-scrape。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (  # noqa: E402
    get_settings,
    list_trip_configs,
    load_agencies_config,
    load_trip_config,
)
from src.db.database import checkpoint_db, checkpoint_db_sync, init_db_sync  # noqa: E402
from src.db.repository import TourRepository  # noqa: E402
from src.discovery import ADAPTER_REGISTRY  # noqa: E402
from src.evaluator.diff_engine import DiffEngine  # noqa: E402
from src.notifier.console import (  # noqa: E402
    print_diff_report,
    print_rankings_table,
    print_recent_diffs,
)
from src.notifier.webhook import send_webhook_digest, send_webhook_notifications  # noqa: E402
from src.schemas.budget_schema import AlertEvent, RankedTourResult  # noqa: E402
from src.schemas.trip_schema import TripConfig  # noqa: E402
from src.services.pipeline_service import PipelineService  # noqa: E402
from src.web.exporter import export_dashboard_json  # noqa: E402

try:
    from rich.console import Console
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("travel-radar")


def _resolve_db_path(cli_db_path: Optional[str]) -> str:
    settings = get_settings()
    return cli_db_path or os.getenv("DATABASE_PATH") or settings.database_path


def cmd_init_db(args: argparse.Namespace) -> int:
    """初始化或安全遷移 SQLite 資料庫。"""
    db_path = _resolve_db_path(args.db_path)
    print(f"\n📦 正在初始化／遷移資料庫: {db_path} (force={args.force})...")
    init_db_sync(db_path=db_path, force=args.force)
    checkpoint_db_sync(db_path=db_path)
    print("✅ 資料庫結構、索引與遷移作業已完成！\n")
    return 0


def cmd_list_trips(args: argparse.Namespace) -> int:
    """列出所有已設定的多目的地旅遊專案。"""
    trips = list_trip_configs(trips_dir=args.trips_dir, enabled_only=False)
    if not trips:
        print(f"\n⚠️ 在 {args.trips_dir} 未找到任何旅遊專案設定檔 (*.yaml)。")
        return 0

    if HAS_RICH:
        console = Console()
        table = Table(
            title=f"🌍 多目的地旅遊專案清單 ({args.trips_dir})",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("專案 ID", style="bold white", no_wrap=True)
        table.add_column("專案名稱", style="cyan", min_width=12)
        table.add_column("目的地", style="green", min_width=8)
        table.add_column("出發區間")
        table.add_column("天數", justify="center")
        table.add_column("佔床年齡", justify="center")
        table.add_column("啟用", justify="center")

        for t in trips:
            table.add_row(
                t.trip_id,
                t.trip_name,
                f"{t.destination.country} / {t.destination.region_name}",
                f"{t.schedule.departure_date_start} ~ {t.schedule.departure_date_end}",
                f"{t.schedule.min_days}~{t.schedule.max_days}天",
                f">={t.party.child_bed_age_threshold}歲",
                "✅" if t.enabled else "⏸️",
            )
        console.print("\n")
        console.print(table)
    else:
        print(f"\n=== 多目的地旅遊專案清單 ({args.trips_dir}) ===")
        for t in trips:
            state = "啟用" if t.enabled else "停用"
            print(
                f"- [{state}] {t.trip_id}: {t.trip_name} | "
                f"{t.destination.country}/{t.destination.region_name} | "
                f"{t.schedule.departure_date_start}~{t.schedule.departure_date_end} | "
                f"{t.schedule.min_days}~{t.schedule.max_days}天 | 佔床>={t.party.child_bed_age_threshold}歲"
            )
    return 0


async def _run_scan_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    db_path = _resolve_db_path(args.db_path)

    # 決定要掃描的旅遊專案清單
    target_trips: List[TripConfig] = []
    if args.trip and args.trip.strip().lower() != "all":
        target_trips.append(load_trip_config(args.trip.strip(), trips_dir=args.trips_dir))
    else:
        target_trips = list_trip_configs(trips_dir=args.trips_dir, enabled_only=True)

    if not target_trips:
        print("⚠️ 目前沒有啟用中的旅遊專案（enabled: true），請檢查 config/trips/*.yaml 或使用 --trip 指定。")
        return 1

    agencies_list: Optional[List[str]] = None
    if args.agency:
        agencies_list = [a.strip() for a in args.agency.split(",") if a.strip()]

    repo = TourRepository(db_path=db_path)
    overall_exit = 0

    for trip_cfg in target_trips:
        print(
            f"\n🔍 啟動旅遊雷達巡檢: [{trip_cfg.trip_id}] {trip_cfg.trip_name} "
            f"({trip_cfg.destination.country} / {trip_cfg.destination.region_name})"
        )
        service = PipelineService(
            settings=settings,
            repository=repo,
            trip_config=trip_cfg,
            allow_playwright_fallback=not args.no_playwright,
        )
        res = await service.run_daily_pipeline(
            agencies=agencies_list,
            force_reparse=args.force_reparse,
            max_new_details_per_run=args.max_details,
            skip_flight_benchmark=args.skip_flights,
            skip_llm=args.skip_llm,
        )

        rankings = [RankedTourResult.model_validate(r) for r in res.get("rankings", [])]
        alerts = [AlertEvent.model_validate(a) for a in res.get("alerts", [])]
        diff_report = DiffEngine.build_report(alerts)
        stats: Dict[str, Any] = res.get("stats", {})

        print_rankings_table(
            rankings,
            title=f"🎯 {trip_cfg.trip_name} ({trip_cfg.destination.region_name}) 排行榜",
        )
        print_diff_report(diff_report)

        dest_desc = f"{trip_cfg.destination.country} {trip_cfg.destination.region_name}".strip()
        if args.notify:
            if diff_report.urgent_alerts:
                send_webhook_notifications(
                    alerts=diff_report.urgent_alerts,
                    trip_name=trip_cfg.trip_name,
                    discord_webhook_url=settings.discord_webhook_url,
                    telegram_bot_token=settings.telegram_bot_token,
                    telegram_chat_id=settings.telegram_chat_id,
                )
            elif args.digest:
                send_webhook_digest(
                    rankings=rankings,
                    agency_stats=stats.get("agencies", {}),
                    trip_name=trip_cfg.trip_name,
                    destination_desc=dest_desc,
                    diff_summary=res.get("diff_summary"),
                    discord_webhook_url=settings.discord_webhook_url,
                    telegram_bot_token=settings.telegram_bot_token,
                    telegram_chat_id=settings.telegram_chat_id,
                )
        elif args.digest:
            send_webhook_digest(
                rankings=rankings,
                agency_stats=stats.get("agencies", {}),
                trip_name=trip_cfg.trip_name,
                destination_desc=dest_desc,
                diff_summary=res.get("diff_summary"),
                discord_webhook_url=settings.discord_webhook_url,
                telegram_bot_token=settings.telegram_bot_token,
                telegram_chat_id=settings.telegram_chat_id,
            )

        print(
            f"✨ [{trip_cfg.trip_id}] 巡檢完成 ({res['status']}) | "
            f"探索 {stats.get('total_discovered', 0)} 筆 | "
            f"新寫入快照 {stats.get('snapshots_inserted', 0)} 筆 | "
            f"告警 {stats.get('alerts_count', 0)} 則"
        )
        if res.get("errors") and stats.get("total_discovered", 0) == 0:
            overall_exit = 1

    await checkpoint_db(db_path)
    if getattr(args, "build_web", False):
        web_summary = await export_dashboard_json(
            output_path=args.web_output,
            db_path=db_path,
            trips_dir=args.trips_dir,
        )
        print(
            f"🌐 已同步更新靜態儀表板資料: {web_summary['output_path']} "
            f"({web_summary['total_active_tours']} 筆行程)"
        )
    return overall_exit


def cmd_scan(args: argparse.Namespace) -> int:
    return asyncio.run(_run_scan_async(args))


async def _run_diff_async(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db_path)
    if not Path(db_path).exists():
        print(f"⚠️ 資料庫不存在 ({db_path})，請先執行 python -m src.cli init-db。")
        return 0
    repo = TourRepository(db_path=db_path)
    diffs = await repo.get_recent_snapshot_diffs(
        hours=args.hours,
        trip_id=args.trip,
        limit=args.limit,
    )
    print_recent_diffs(diffs, hours=args.hours)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    return asyncio.run(_run_diff_async(args))


async def _run_test_scrape_async(args: argparse.Namespace) -> int:
    agencies_cfg = load_agencies_config("config/agencies.yaml")
    agency_cfg = agencies_cfg.get("agencies", {}).get(args.agency)
    concurrency_cfg = agencies_cfg.get("concurrency", {})
    cls = ADAPTER_REGISTRY.get(args.agency)
    if cls is None or agency_cfg is None:
        print(f"❌ 不支援或未設定的旅行社代碼: {args.agency}")
        return 1

    trip_cfg: Optional[TripConfig] = None
    common_filters: Dict[str, Any] = {}
    if args.trip:
        trip_cfg = load_trip_config(args.trip, trips_dir=args.trips_dir)
    elif args.keyword:
        common_filters = {"destination_keywords": [args.keyword]}
    else:
        enabled_trips = list_trip_configs(trips_dir=args.trips_dir, enabled_only=True)
        if enabled_trips:
            trip_cfg = enabled_trips[0]

    adapter = cls(
        agency_config=agency_cfg,
        common_filters=common_filters,
        concurrency_config=concurrency_cfg,
        trip_config=trip_cfg,
        allow_playwright_fallback=not args.no_playwright,
    )

    print(
        f"\n🧪 獨立測試爬蟲 [{adapter.agency_name}] "
        f"(keyword={adapter.get_search_keywords() or ['不限']}, "
        f"days={adapter.get_min_days()}~{adapter.get_max_days()}, "
        f"playwright_fallback={not args.no_playwright})..."
    )
    items, mode = await adapter.fetch_tours()
    print(f"✅ 抓取成功 (mode={mode})，共取得 {len(items)} 筆行程（未寫入資料庫）：\n")
    for idx, item in enumerate(items[:20], 1):
        price_str = f"NT${item.adult_price:,}" if item.adult_price else "價格未標"
        seats_str = f"餘{item.seats_available}席" if item.seats_available is not None else item.status
        print(
            f"  [{idx}] {item.tour_code} | {item.departure_date} ({item.days}日) | "
            f"{item.departure_airport} | {price_str} | {seats_str} | {item.tour_name}"
        )
    if len(items) > 20:
        print(f"\n  ... 另有 {len(items) - 20} 筆未列出")
    return 0


def cmd_test_scrape(args: argparse.Namespace) -> int:
    return asyncio.run(_run_test_scrape_async(args))


async def _run_build_web_async(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db_path)
    summary = await export_dashboard_json(
        output_path=args.output,
        db_path=db_path,
        trips_dir=args.trips_dir,
        diff_hours=args.diff_hours,
    )
    print(
        f"\n🌐 靜態網頁儀表板資料匯出完成：{summary['output_path']}\n"
        f"   - 專案數：{summary['trips_count']} | 活躍團次：{summary['total_active_tours']} "
        f"| 近期異動：{summary['diffs_count']} | 檔案大小：{summary['bytes_written']:,} bytes\n"
    )
    return 0


def cmd_build_web(args: argparse.Namespace) -> int:
    return asyncio.run(_run_build_web_async(args))


def cmd_serve(args: argparse.Namespace) -> int:
    """啟動本機 FastAPI 伺服器並掛載網頁儀表板。"""
    import uvicorn

    if args.db_path:
        os.environ["DATABASE_PATH"] = args.db_path
        get_settings.cache_clear()

    resolved_db = _resolve_db_path(args.db_path)
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(
        f"\n🚀 啟動 Travel Radar Live Web 伺服器...\n"
        f"   👉 儀表板網址：http://{display_host}:{args.port}\n"
        f"   👉 API 文件：  http://{display_host}:{args.port}/docs\n"
        f"   👉 資料庫路徑：{resolved_db}\n"
    )
    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="travel-radar",
        description="通用多目的地旅遊比價與異動監控雷達 (Travel Radar CLI)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="可用子指令")

    # init-db
    p_init = subparsers.add_parser("init-db", help="初始化或安全遷移 SQLite 資料庫")
    p_init.add_argument("--db-path", default=None, help="資料庫路徑 (預設讀 DATABASE_PATH 或 data/radar.db)")
    p_init.add_argument("--force", action="store_true", help="強制刪除並重建全新資料庫")
    p_init.set_defaults(func=cmd_init_db)

    # list-trips
    p_trips = subparsers.add_parser("list-trips", help="列出所有已設定的旅遊專案 YAML")
    p_trips.add_argument("--trips-dir", default="config/trips", help="旅遊專案設定目錄")
    p_trips.set_defaults(func=cmd_list_trips)

    # scan
    p_scan = subparsers.add_parser("scan", help="執行巡檢、預算試算、規則評分、快照比對與推播")
    p_scan.add_argument("--trip", default=None, help="指定旅遊專案 ID 或 YAML 路徑（傳 'all' 等同 --all）")
    p_scan.add_argument("--all", action="store_true", help="巡檢所有 enabled: true 的旅遊專案")
    p_scan.add_argument("--trips-dir", default="config/trips", help="旅遊專案設定目錄")
    p_scan.add_argument("--agency", default=None, help="限定旅行社代碼（逗號分隔，如 lion,richmont）")
    p_scan.add_argument("--notify", action="store_true", help="有重大異動時發送 Discord/Telegram 警報")
    p_scan.add_argument("--digest", action="store_true", help="無重大異動時發送每日健康心跳與 Top 5 摘要")
    p_scan.add_argument("--skip-llm", action="store_true", help="略過詳情頁 LLM 解析（Zero-Infra 快速模式）")
    p_scan.add_argument("--skip-flights", action="store_true", help="略過 Google Flights 機票基準查詢")
    p_scan.add_argument("--no-playwright", action="store_true", help="停用 Playwright 降級，僅跑 httpx XHR/SSR")
    p_scan.add_argument("--force-reparse", action="store_true", help="強制忽略 7 天快取並重新解析詳情")
    p_scan.add_argument("--max-details", type=int, default=None, help="單次最多解析新詳情頁數量上限")
    p_scan.add_argument("--db-path", default=None, help="資料庫路徑 (預設 data/radar.db)")
    p_scan.add_argument("--build-web", action="store_true", help="掃描完成後順便匯出 web/data/dashboard.json")
    p_scan.add_argument("--web-output", default="web/data/dashboard.json", help="靜態儀表板 JSON 輸出路徑")
    p_scan.set_defaults(func=cmd_scan)

    # diff
    p_diff = subparsers.add_parser("diff", help="查詢近期價格、機位與狀態快照異動紀錄")
    p_diff.add_argument("--trip", default=None, help="依 trip_id 篩選")
    p_diff.add_argument("--hours", type=int, default=24, help="查詢過去幾小時內的異動 (預設 24)")
    p_diff.add_argument("--limit", type=int, default=30, help="最多顯示筆數 (預設 30)")
    p_diff.add_argument("--db-path", default=None, help="資料庫路徑 (預設 data/radar.db)")
    p_diff.set_defaults(func=cmd_diff)

    # test-scrape
    p_test = subparsers.add_parser("test-scrape", help="單一旅行社獨立除錯（不寫入資料庫）")
    p_test.add_argument(
        "--agency",
        required=True,
        choices=list(ADAPTER_REGISTRY.keys()),
        help="旅行社代碼",
    )
    p_test.add_argument("--trip", default=None, help="套用的旅遊專案 ID 或 YAML 路徑")
    p_test.add_argument("--trips-dir", default="config/trips", help="旅遊專案設定目錄")
    p_test.add_argument("--keyword", default=None, help="自訂搜尋關鍵字（未指定 --trip 時使用）")
    p_test.add_argument("--no-playwright", action="store_true", help="停用 Playwright 降級")
    p_test.set_defaults(func=cmd_test_scrape)

    # build-web
    p_web = subparsers.add_parser("build-web", help="將 SQLite 資料匯出為靜態網頁儀表板 JSON")
    p_web.add_argument("--db-path", default=None, help="資料庫路徑 (預設 data/radar.db)")
    p_web.add_argument("--trips-dir", default="config/trips", help="旅遊專案設定目錄")
    p_web.add_argument("--output", default="web/data/dashboard.json", help="輸出 JSON 路徑")
    p_web.add_argument("--diff-hours", type=int, default=168, help="匯出過去幾小時內的異動紀錄 (預設 168)")
    p_web.set_defaults(func=cmd_build_web)

    # serve
    p_serve = subparsers.add_parser("serve", help="啟動本機 FastAPI Live 網頁儀表板")
    p_serve.add_argument("--host", default="127.0.0.1", help="監聽位址 (預設 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="監聽埠號 (預設 8000)")
    p_serve.add_argument("--reload", action="store_true", help="啟用開發自動重載")
    p_serve.add_argument("--db-path", default=None, help="指定資料庫路徑 (預設讀 .env 或 data/radar.db)")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 1
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
