from __future__ import annotations

from typing import Any, Dict, List

from src.evaluator.diff_engine import DiffReport
from src.schemas.budget_schema import RankedTourResult

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False


def print_rankings_table(
    rankings: List[RankedTourResult],
    title: str = "🎯 旅遊比價雷達 — 推薦行程排行榜",
    limit: int = 20,
) -> None:
    """終端輸出格式化行程排行榜（Rich -> tabulate -> 純文字三段降級）。"""
    if not rankings:
        print(f"\n⚠️ [{title}] 未發現符合條件之行程。")
        return

    shown = rankings[:limit]

    if HAS_RICH:
        console = Console()
        table = Table(
            title=title,
            show_header=True,
            header_style="bold magenta",
            border_style="bright_blue",
        )
        table.add_column("旅行社", style="cyan", width=8)
        table.add_column("行程標題", style="bold white", min_width=24)
        table.add_column("出發日", style="green", width=11)
        table.add_column("天數", justify="right", width=5)
        table.add_column("機場", justify="center", width=5)
        table.add_column("成人價", justify="right", style="yellow", width=10)
        table.add_column("家族總價", justify="right", style="bold green", width=12)
        table.add_column("機位/狀態", justify="center", width=12)
        table.add_column("評分", justify="right", style="bold yellow", width=6)
        table.add_column("標籤", style="dim", width=20)

        for r in shown:
            adult_str = f"NT${r.adult_price:,}" if r.adult_price else "-"
            total_str = f"NT${r.budget.grand_total_twd:,}"
            seats_str = str(r.seats_available) if r.seats_available is not None else "?"
            status_color = "bold green" if r.status in {"保證出團", "可報名"} else "bold red"
            status_cell = f"[{status_color}]{r.status}[/{status_color}]\n(餘{seats_str}席)"
            tags_str = " ".join(f"#{t}" for t in r.tags[:3])

            table.add_row(
                r.agency,
                r.tour_name[:36],
                r.departure_date,
                f"{r.days}日",
                r.departure_airport,
                adult_str,
                total_str,
                status_cell,
                f"{r.composite_score:.1f}",
                tags_str,
            )

        console.print("\n")
        console.print(table)
        console.print(f"[dim]共 {len(rankings)} 筆行程，顯示前 {len(shown)} 筆[/dim]\n")

    elif HAS_TABULATE:
        headers = ["旅行社", "行程標題", "出發日", "天數", "機場", "成人價", "家族總價", "狀態/機位", "評分", "標籤"]
        rows = []
        for r in shown:
            rows.append([
                r.agency,
                r.tour_name[:28],
                r.departure_date,
                f"{r.days}日",
                r.departure_airport,
                f"{r.adult_price:,}" if r.adult_price else "-",
                f"{r.budget.grand_total_twd:,}",
                f"{r.status}({r.seats_available if r.seats_available is not None else '?'})",
                f"{r.composite_score:.1f}",
                ",".join(r.tags[:3]),
            ])
        print(f"\n=== {title} ===")
        print(tabulate(rows, headers=headers, tablefmt="grid"))
        print(f"共 {len(rankings)} 筆，顯示前 {len(shown)} 筆\n")

    else:
        print(f"\n=== {title} ===")
        for idx, r in enumerate(shown, 1):
            adult_str = f"NT${r.adult_price:,}" if r.adult_price else "-"
            print(
                f"[{idx}] {r.agency} | {r.tour_name} | {r.departure_date} ({r.days}日) | "
                f"{r.departure_airport} | 成人:{adult_str} | 家族總價:NT${r.budget.grand_total_twd:,} | "
                f"{r.status}({r.seats_available}) | 評分:{r.composite_score:.1f}"
            )


def print_diff_report(diff_report: DiffReport) -> None:
    """印出本次巡檢偵測到的價格與名額差異告警。"""
    if diff_report.total_count == 0:
        print("ℹ️ 本次巡檢無新增或價格／名額異動告警。")
        return

    sections = [
        ("💰 【大幅降價】價格調降通知", diff_report.price_drops, "bold green"),
        ("🎉 【名額釋出】滿團／候補釋出位子", diff_report.seats_released, "bold cyan"),
        ("✅ 【成團通知】升級為保證出團", diff_report.guaranteed_departures, "bold blue"),
        ("🆕 【新團上架】新行程發現", diff_report.new_tours, "cyan"),
        ("⚠️ 【機位警示】機位預警與告急", diff_report.low_seats, "bold yellow"),
        ("🛠️ 【維運提示】異常與系統事件", diff_report.other_alerts, "dim white"),
    ]

    if HAS_RICH:
        console = Console()
        for header, items, style in sections:
            if not items:
                continue
            body = "\n".join(f"• [{ev.tour_uid or 'SYSTEM'}] {ev.message}" for ev in items[:15])
            if len(items) > 15:
                body += f"\n... 另有 {len(items) - 15} 筆同類告警"
            console.print(Panel(body, title=header, style=style))
    else:
        for header, items, _ in sections:
            if not items:
                continue
            print(f"\n{header}:")
            for ev in items[:15]:
                print(f"  - [{ev.tour_uid or 'SYSTEM'}] {ev.message}")


def print_recent_diffs(diffs: List[Dict[str, Any]], hours: int = 24) -> None:
    """供 CLI diff 指令印出歷史快照差異表。"""
    if not diffs:
        print(f"ℹ️ 過去 {hours} 小時內無價格或機位狀態異動紀錄。")
        return

    title = f"📊 過去 {hours} 小時價格／機位／狀態異動紀錄"
    if HAS_RICH:
        console = Console()
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("時間", width=19)
        table.add_column("專案", width=16)
        table.add_column("旅行社", width=8)
        table.add_column("行程", min_width=20)
        table.add_column("出發日", width=10)
        table.add_column("成人價變化", justify="right", width=18)
        table.add_column("機位變化", justify="center", width=12)
        table.add_column("狀態變化", width=16)

        for d in diffs:
            old_p = f"{d['old_price']:,}" if d.get("old_price") is not None else "新"
            new_p = f"{d['new_price']:,}" if d.get("new_price") is not None else "-"
            old_s = str(d["old_seats"]) if d.get("old_seats") is not None else "-"
            new_s = str(d["new_seats"]) if d.get("new_seats") is not None else "-"
            old_st = d.get("old_status") or "無"
            new_st = d.get("new_status") or "未知"
            table.add_row(
                str(d.get("captured_at", ""))[:19],
                str(d.get("trip_id", "default")),
                str(d.get("agency", "")),
                str(d.get("tour_name", ""))[:26],
                str(d.get("departure_date", "")),
                f"{old_p} -> {new_p}",
                f"{old_s} -> {new_s}",
                f"{old_st} -> {new_st}",
            )
        console.print("\n")
        console.print(table)
    elif HAS_TABULATE:
        headers = ["時間", "專案", "旅行社", "行程", "出發日", "價格變化", "機位變化", "狀態變化"]
        rows = []
        for d in diffs:
            rows.append([
                str(d.get("captured_at", ""))[:19],
                d.get("trip_id", "default"),
                d.get("agency", ""),
                str(d.get("tour_name", ""))[:22],
                d.get("departure_date", ""),
                f"{d.get('old_price')} -> {d.get('new_price')}",
                f"{d.get('old_seats')} -> {d.get('new_seats')}",
                f"{d.get('old_status') or '無'} -> {d.get('new_status')}",
            ])
        print(f"\n=== {title} ===")
        print(tabulate(rows, headers=headers, tablefmt="grid"))
    else:
        print(f"\n=== {title} ===")
        for d in diffs:
            print(
                f"{str(d.get('captured_at', ''))[:19]} | {d.get('trip_id')} | {d.get('agency')} | "
                f"{d.get('tour_name')} | 價:{d.get('old_price')}->{d.get('new_price')} | "
                f"席:{d.get('old_seats')}->{d.get('new_seats')} | 態:{d.get('old_status')}->{d.get('new_status')}"
            )
